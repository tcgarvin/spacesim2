"""LiveGalaxyApp: window, main loop, and input for the live galaxy view.

Holds the pygame window, a fixed-timestep-ish clock, the camera, the director
(turn pacing), and the galaxy scene. Input is restrained: play/pause, speed,
zoom, pan, quit. ``initialize`` / ``update`` / ``render`` are split out so tests
can drive frames headlessly (``SDL_VIDEODRIVER=dummy``) without the blocking loop.
"""

from __future__ import annotations

from typing import Optional, Tuple

from spacesim2.core.simulation import Simulation

try:
    import pygame

    PYGAME_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without pygame installed
    PYGAME_AVAILABLE = False

from spacesim2.ui.live.camera import Camera
from spacesim2.ui.live.director import Director
from spacesim2.ui.live.scenes.galaxy_scene import GalaxyScene
from spacesim2.ui.live.view_model import GalaxyViewModel

DEFAULT_SIZE = (1600, 900)
TARGET_FPS = 60
ZOOM_STEP = 1.1


class LiveGalaxyApp:
    def __init__(
        self,
        simulation: Simulation,
        speed: float = 1.0,
        paused: bool = False,
        size: Tuple[int, int] = DEFAULT_SIZE,
    ) -> None:
        self._sim = simulation
        self._speed = speed
        self._paused = paused
        self._size = size

        self._screen: Optional[pygame.Surface] = None
        self._clock: Optional[pygame.time.Clock] = None
        self._camera: Optional[Camera] = None
        self._director: Optional[Director] = None
        self._scene: Optional[GalaxyScene] = None
        self._running = False
        self._dragging = False
        self._last_mouse: Tuple[int, int] = (0, 0)

    def initialize(self) -> None:
        pygame.init()
        pygame.font.init()
        self._screen = pygame.display.set_mode(self._size, pygame.RESIZABLE)
        pygame.display.set_caption("SpaceSim2 — Live Galaxy")
        self._clock = pygame.time.Clock()

        view_model = GalaxyViewModel(self._sim)
        self._camera = Camera(self._size)
        self._director = Director(
            self._sim,
            view_model,
            turns_per_second=self._speed,
            paused=self._paused,
        )
        self._scene = GalaxyScene(view_model, self._director, self._camera, self._size)

    def handle_event(self, event: "pygame.event.Event") -> bool:
        """Process one event. Returns False if the app should quit."""
        assert self._camera is not None and self._director is not None
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_q):
                return False
            if event.key == pygame.K_SPACE:
                self._director.toggle_pause()
            elif event.key in (pygame.K_PLUS, pygame.K_EQUALS):
                self._director.change_speed(2.0)
            elif event.key == pygame.K_MINUS:
                self._director.change_speed(0.5)
            elif event.key == pygame.K_TAB:
                assert self._scene is not None
                self._scene.charts.toggle()
            elif event.key in (pygame.K_RIGHTBRACKET, pygame.K_RIGHT):
                assert self._scene is not None
                self._scene.charts.cycle_commodity(1)
            elif event.key in (pygame.K_LEFTBRACKET, pygame.K_LEFT):
                assert self._scene is not None
                self._scene.charts.cycle_commodity(-1)
        elif event.type == pygame.MOUSEWHEEL:
            factor = ZOOM_STEP if event.y > 0 else 1.0 / ZOOM_STEP
            self._camera.zoom_at(pygame.mouse.get_pos(), factor)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._dragging = True
            self._last_mouse = event.pos
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._dragging = False
        elif event.type == pygame.MOUSEMOTION and self._dragging:
            dx = event.pos[0] - self._last_mouse[0]
            dy = event.pos[1] - self._last_mouse[1]
            self._camera.pan_pixels(dx, dy)
            self._last_mouse = event.pos
        elif event.type == pygame.VIDEORESIZE:
            self._resize((event.w, event.h))
        return True

    def _resize(self, size: Tuple[int, int]) -> None:
        assert self._scene is not None
        self._size = size
        self._screen = pygame.display.set_mode(size, pygame.RESIZABLE)
        self._scene.resize(size)

    def update(self, dt: float) -> None:
        assert self._director is not None
        self._director.update(dt)

    def render(self) -> None:
        assert self._screen is not None and self._scene is not None
        self._scene.draw(self._screen)
        pygame.display.flip()

    def run(self) -> None:
        self.initialize()
        assert self._clock is not None
        self._running = True
        while self._running:
            dt = self._clock.tick(TARGET_FPS) / 1000.0
            for event in pygame.event.get():
                if not self.handle_event(event):
                    self._running = False
                    break
            self.update(dt)
            self.render()
        pygame.quit()
