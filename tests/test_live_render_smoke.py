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

from spacesim2.core.ship import ShipStatus  # noqa: E402
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


def test_baked_ship_sprites_and_good_icons_render() -> None:
    """The committed sprite/icon assets exercise the baked path by default.

    Forces a ship into travel (so a non-zero-heading directional frame renders)
    and opens both a planet panel (market-row icons) and the ship panel
    (hold-row icons), asserting the frame stays exception-free and non-blank.
    """
    sim = _sim()
    app = LiveGalaxyApp(sim, speed=4.0, size=(900, 600))
    try:
        app.initialize()
        assert app._scene is not None
        # Committed assets must actually be loaded, not silently skipped.
        assert app._scene._ship_sprites
        assert app._scene._good_icons

        # Give a ship cargo so the hold section renders an icon row.
        ship = sim.ships[0]
        food = sim.commodity_registry["food"]
        ship.cargo.add_commodity(food, 3)

        for _ in range(5):
            app.update(0.05)
            app.render()

        # Put the ship in transit so a non-zero-heading directional frame
        # renders. Set this *after* the update loop and only render below, so no
        # turn advances against the forced (travel_time-less) travel state.
        ship.planet = sim.planets[0]
        ship.destination = sim.planets[1]
        ship.status = ShipStatus.TRAVELING
        ship.travel_progress = 0.4
        app.render()

        # Render a planet panel (market icons) then the ship panel (hold icons).
        app._scene.selection = ("planet", sim.planets[0].name)
        app.render()
        app._scene.selection = ("ship", ship.name)
        app.render()

        assert app._screen is not None
        frame = pygame.surfarray.array3d(app._screen)
        assert frame.std() > 1.0
        assert int(np.max(frame.sum(axis=2))) > 30
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


def test_click_planet_selects_and_renders_detail_panel() -> None:
    sim = _sim()
    app = LiveGalaxyApp(sim, size=(900, 600))
    try:
        app.initialize()
        assert app._scene is not None and app._camera is not None
        planet = sim.planets[0]
        pos = app._camera.world_to_screen(planet.get_position())

        down = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)
        up = pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos)
        assert app.handle_event(down) is True
        assert app.handle_event(up) is True
        assert app._scene.selection == ("planet", planet.name)

        # Panel + planet-scoped charts render without error.
        app.render()
        assert app._scene._panel_rect is not None

        # Esc closes the panel first (app keeps running)...
        esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
        assert app.handle_event(esc) is True
        assert app._scene.selection is None
        # ...and quits once nothing is open.
        assert app.handle_event(esc) is False
    finally:
        pygame.quit()


def test_drag_does_not_select() -> None:
    sim = _sim()
    app = LiveGalaxyApp(sim, size=(900, 600))
    try:
        app.initialize()
        assert app._scene is not None and app._camera is not None
        planet = sim.planets[0]
        pos = app._camera.world_to_screen(planet.get_position())
        far = (pos[0] + 60, pos[1] + 60)

        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos))
        app.handle_event(
            pygame.event.Event(
                pygame.MOUSEMOTION, pos=far, rel=(60, 60), buttons=(1, 0, 0)
            )
        )
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=far))
        assert app._scene.selection is None
    finally:
        pygame.quit()


def test_click_void_clears_selection_and_ship_pick_works() -> None:
    sim = _sim()
    app = LiveGalaxyApp(sim, size=(900, 600))
    try:
        app.initialize()
        scene = app._scene
        assert scene is not None and app._camera is not None

        # Ship picking: dock position of a known ship.
        ship = sim.ships[0]
        assert ship.planet is not None
        ship_pos = app._camera.world_to_screen(ship.planet.get_position())
        picked = scene.pick(ship_pos)
        # The planet sits on top of its docked ships, so the planet wins here.
        assert picked is not None and picked[0] == "planet"

        scene.selection = ("ship", ship.name)
        app.render()  # ship panel renders without error
        assert scene._panel_rect is not None

        # Find a void spot (no pick) and click it: selection clears.
        void = None
        for x in range(10, 900, 40):
            for y in range(10, 600, 40):
                if scene.pick((x, y)) is None and not (
                    scene._panel_rect and scene._panel_rect.collidepoint((x, y))
                ):
                    void = (x, y)
                    break
            if void:
                break
        assert void is not None
        scene.handle_click(void)
        assert scene.selection is None
    finally:
        pygame.quit()
