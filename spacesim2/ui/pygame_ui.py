from typing import Optional, Literal, Dict, List, Tuple, Any
import pygame
from pygame import Rect, Color

try:
    pygame.init()
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False
    print("Warning: pygame not installed. Only headless mode available.")

from spacesim2.core.actor import Actor
from spacesim2.core.commodity import CommodityDefinition
from spacesim2.core.simulation import Simulation
from spacesim2.core.planet import Planet
from spacesim2.core.ship import Ship, ShipStatus

# Import UI components
from spacesim2.ui.utils.colors import ColorManager
from spacesim2.ui.utils.text import TextRenderer
from spacesim2.ui.utils.input_handler import InputHandler
from spacesim2.ui.renderers.ui_renderer import UIRenderer
from spacesim2.ui.components.actor_list import ActorListPanel
from spacesim2.ui.components.ship_list import ShipListPanel
from spacesim2.ui.components.planet_view import PlanetViewPanel
from spacesim2.ui.components.detail_panel import DetailPanel
from spacesim2.ui.components.status_bar import StatusBar

# UI screen modes
ScreenMode = Literal["main", "actor_details"]


class PygameUI:
    """Graphical user interface using pygame."""

    def __init__(self, simulation: Simulation) -> None:
        """Initialize the Pygame UI.
        
        Args:
            simulation: The simulation to visualize
        """
        self.simulation = simulation
        
        # Screen dimensions
        self.width = 1920
        self.height = 1080
        
        # Pane dimensions
        self.left_pane_width = 640
        self.center_pane_width = 640
        self.right_pane_width = 640
        
        # UI state
        self.active_pane = 1  # 0=left, 1=center, 2=right
        self.selected_planet: Optional[Planet] = None
        self.selected_actor: Optional[Actor] = None
        self.selected_ship: Optional[Ship] = None
        self.selected_commodity: Optional[CommodityDefinition] = None
        self.view_ships = False  # Toggle between viewing actors and ships in the left pane
        
        # Initialize color manager
        self.color_manager = ColorManager()
        self.colors = self.color_manager.colors
        
        # Pygame objects
        self.screen: Optional[pygame.Surface] = None
        self.fonts: Dict[str, pygame.font.Font] = {}
        self.clock: Optional[pygame.time.Clock] = None
        self.running = False
        
        # UI components
        self.text_renderer: Optional[TextRenderer] = None
        self.input_handler: Optional[InputHandler] = None
        self.ui_renderer: Optional[UIRenderer] = None
        self.actor_list_panel: Optional[ActorListPanel] = None
        self.ship_list_panel: Optional[ShipListPanel] = None
        self.planet_view_panel: Optional[PlanetViewPanel] = None
        self.detail_panel: Optional[DetailPanel] = None
        self.status_bar: Optional[StatusBar] = None

    def initialize(self) -> bool:
        """Initialize pygame and set up the window."""
        if not PYGAME_AVAILABLE:
            return False

        pygame.init()
        pygame.display.set_caption("SpaceSim2")
        self.screen = pygame.display.set_mode((self.width, self.height))
        
        # Initialize text renderer
        self.text_renderer = TextRenderer()
        self.text_renderer.initialize()
        
        # Initialize input handler
        self.input_handler = InputHandler()
        self._register_input_handlers()
        
        # Initialize UI renderer
        self.ui_renderer = UIRenderer(self.screen, self.colors)
        
        # Initialize UI components
        self._initialize_components()
        
        # Set up clock
        self.clock = pygame.time.Clock()
        
        # Select first planet by default
        if self.simulation.planets:
            self.selected_planet = self.simulation.planets[0]
            self._update_selected_planet(self.selected_planet)
        
        return True
        
    def _initialize_components(self) -> None:
        """Initialize all UI components."""
        # Left pane components
        self.actor_list_panel = ActorListPanel(
            self.screen, self.text_renderer.fonts, self.colors, 
            self.left_pane_width, self.height
        )
        self.ship_list_panel = ShipListPanel(
            self.screen, self.text_renderer.fonts, self.colors, 
            self.left_pane_width, self.height
        )
        
        # Center pane
        self.planet_view_panel = PlanetViewPanel(
            self.screen, self.colors,
            self.left_pane_width, 0, self.center_pane_width, self.height
        )
        self.planet_view_panel.set_planets(self.simulation.planets)
        
        # Right pane
        self.detail_panel = DetailPanel(
            self.screen, self.colors,
            self.left_pane_width + self.center_pane_width, 0, 
            self.right_pane_width, self.height
        )
        self.detail_panel.set_simulation(self.simulation)
        
        # Status bar
        self.status_bar = StatusBar(
            self.screen, self.colors, self.width, self.height
        )
        self.status_bar.set_simulation(self.simulation)
    
    def _register_input_handlers(self) -> None:
        """Register input event handlers."""
        if not self.input_handler:
            return
            
        # Register key handlers
        self.input_handler.register_key_callback(pygame.K_ESCAPE, self._handle_escape)
        self.input_handler.register_key_callback(pygame.K_SPACE, self._handle_space)
        self.input_handler.register_key_callback(pygame.K_TAB, self._handle_tab)
        self.input_handler.register_key_callback(pygame.K_LEFT, self._handle_left)
        self.input_handler.register_key_callback(pygame.K_RIGHT, self._handle_right)
        self.input_handler.register_key_callback(pygame.K_UP, self._handle_up)
        self.input_handler.register_key_callback(pygame.K_DOWN, self._handle_down)
        self.input_handler.register_key_callback(pygame.K_s, self._handle_toggle_ships)
        self.input_handler.register_key_callback(pygame.K_RETURN, self._handle_enter)
        
        # Register mouse handlers
        self.input_handler.register_mouse_click_callback(1, self._handle_mouse_click)
        
        # Register scroll handlers
        self.input_handler.register_mouse_scroll_callback(4, self._handle_scroll_up)
        self.input_handler.register_mouse_scroll_callback(5, self._handle_scroll_down)
        
        # Register quit handlers
        self.input_handler.register_quit_callback(self._handle_quit)
    
    def _handle_escape(self, event: pygame.event.Event) -> bool:
        """Handle Escape key.
        
        Returns:
            False to indicate the application should quit
        """
        self.running = False
        return False
    
    def _handle_space(self, event: pygame.event.Event) -> None:
        """Handle Space key to advance simulation."""
        self.simulation.run_turn()
    
    def _handle_tab(self, event: pygame.event.Event) -> None:
        """Handle Tab key to cycle through panes."""
        self.active_pane = (self.active_pane + 1) % 3
    
    def _handle_left(self, event: pygame.event.Event) -> None:
        """Handle Left key."""
        # Move to left pane
        if self.active_pane > 0:
            self.active_pane -= 1
        else:
            # Handle navigation within the active pane
            self._handle_navigation_in_active_pane(event.key)
    
    def _handle_right(self, event: pygame.event.Event) -> None:
        """Handle Right key."""
        # Move to right pane
        if self.active_pane < 2:
            self.active_pane += 1
        else:
            # Handle navigation within the active pane
            self._handle_navigation_in_active_pane(event.key)
    
    def _handle_up(self, event: pygame.event.Event) -> None:
        """Handle Up key."""
        self._handle_navigation_in_active_pane(event.key)
    
    def _handle_down(self, event: pygame.event.Event) -> None:
        """Handle Down key."""
        self._handle_navigation_in_active_pane(event.key)
    
    def _handle_enter(self, event: pygame.event.Event) -> None:
        """Handle Enter key."""
        if self.active_pane == 1:  # Center pane (planet grid)
            # Focus on left pane to select an actor
            self.active_pane = 0
        else:
            # Handle navigation within the active pane
            self._handle_navigation_in_active_pane(event.key)
    
    def _handle_toggle_ships(self, event: pygame.event.Event) -> None:
        """Handle S key to toggle between actors and ships view."""
        self.view_ships = not self.view_ships
        if self.view_ships:
            self.selected_actor = None
        else:
            self.selected_ship = None
    
    def _handle_mouse_click(self, event: pygame.event.Event) -> None:
        """Handle mouse click."""
        x, y = event.pos
        
        # Determine which pane was clicked
        if x < self.left_pane_width:
            self.active_pane = 0
            # Handle actor/ship selection in left pane
            if self.view_ships and self.ship_list_panel:
                self.ship_list_panel.handle_click(x, y)
                self.selected_ship = self.ship_list_panel.selected_ship
                if self.selected_ship:
                    self.selected_actor = None
            else:
                if self.actor_list_panel:
                    self.actor_list_panel.handle_click(x, y)
                    self.selected_actor = self.actor_list_panel.selected_actor
                    if self.selected_actor:
                        self.selected_ship = None
        elif x < self.left_pane_width + self.center_pane_width:
            self.active_pane = 1
            # Handle planet selection in center pane
            if self.planet_view_panel:
                if self.planet_view_panel.handle_click(x, y):
                    self.selected_planet = self.planet_view_panel.selected_planet
                    self._update_selected_planet(self.selected_planet)
        else:
            self.active_pane = 2
            # Handle detail pane interaction
            if self.detail_panel:
                self.detail_panel.handle_click(x, y)
                self.selected_commodity = self.detail_panel.selected_commodity
    
    def _handle_scroll_up(self, event: pygame.event.Event) -> None:
        """Handle scroll up."""
        if self.active_pane == 0:  # Left pane
            if self.view_ships and self.ship_list_panel:
                self.ship_list_panel.scroll_up()
            elif self.actor_list_panel:
                self.actor_list_panel.scroll_up()
    
    def _handle_scroll_down(self, event: pygame.event.Event) -> None:
        """Handle scroll down."""
        if self.active_pane == 0:  # Left pane
            if self.view_ships and self.ship_list_panel:
                self.ship_list_panel.scroll_down()
            elif self.actor_list_panel:
                self.actor_list_panel.scroll_down()
    
    def _handle_quit(self) -> None:
        """Handle quit event."""
        self.running = False
    
    def _handle_navigation_in_active_pane(self, key: int) -> None:
        """Handle navigation keys within the active pane."""
        if self.active_pane == 0:  # Left pane (actor/ship list)
            if self.view_ships and self.ship_list_panel:
                if self.ship_list_panel.handle_key(key):
                    self.selected_ship = self.ship_list_panel.selected_ship
            elif self.actor_list_panel:
                if self.actor_list_panel.handle_key(key):
                    self.selected_actor = self.actor_list_panel.selected_actor
        
        elif self.active_pane == 1:  # Center pane (planet grid)
            if self.planet_view_panel:
                if self.planet_view_panel.handle_key(key):
                    self.selected_planet = self.planet_view_panel.selected_planet
                    self._update_selected_planet(self.selected_planet)
        
        elif self.active_pane == 2:  # Right pane (detail view)
            if self.detail_panel:
                if self.detail_panel.handle_key(key):
                    self.selected_commodity = self.detail_panel.selected_commodity
    
    def _update_selected_planet(self, planet: Optional[Planet]) -> None:
        """Update all components with the newly selected planet."""
        if not planet:
            return
            
        if self.actor_list_panel:
            self.actor_list_panel.set_selected_planet(planet)
            self.actor_list_panel.set_selected_actor(None)
            
        if self.ship_list_panel:
            self.ship_list_panel.set_selected_planet(planet)
            self.ship_list_panel.set_selected_ship(None)
            
        if self.planet_view_panel:
            self.planet_view_panel.set_selected_planet(planet)
            
        if self.detail_panel:
            self.detail_panel.set_selected_planet(planet)
            self.detail_panel.set_selected_actor(None)
            self.detail_panel.set_selected_ship(None)
            
        # Clear selections
        self.selected_actor = None
        self.selected_ship = None
        self.selected_commodity = None

    def handle_events(self) -> bool:
        """Handle pygame events. Return False to quit."""
        if not self.input_handler:
            return False
            
        return self.input_handler.handle_events()

    def render(self) -> None:
        """Render the current state of the simulation."""
        if not self.screen or not self.text_renderer:
            return

        # Clear screen with background color
        self.screen.fill(self.colors["background"])
        
        # Draw pane backgrounds with active highlight
        if self.ui_renderer:
            pane_dimensions = {
                "left_width": self.left_pane_width,
                "center_width": self.center_pane_width,
                "right_width": self.right_pane_width,
                "height": self.height
            }
            self.ui_renderer.draw_pane_backgrounds(self.active_pane, pane_dimensions)
        
        # Render each component
        if self.view_ships:
            if self.ship_list_panel:
                self.ship_list_panel.render(self.text_renderer)
        else:
            if self.actor_list_panel:
                self.actor_list_panel.render(self.text_renderer)
                
        if self.planet_view_panel:
            self.planet_view_panel.render(self.text_renderer, self.simulation.ships)
            
        if self.detail_panel:
            # Update selected objects in case they changed
            self.detail_panel.set_selected_actor(self.selected_actor)
            self.detail_panel.set_selected_ship(self.selected_ship)
            self.detail_panel.set_selected_commodity(self.selected_commodity)
            self.detail_panel.render(self.text_renderer)
            
        if self.status_bar:
            self.status_bar.render(self.text_renderer)
        
        # Update display
        pygame.display.flip()

    def run(self, auto_turns: int = 0) -> None:
        """Run the pygame UI loop.

        Args:
            auto_turns: If greater than 0, automatically run this many turns
                        and then wait for user input.
        """
        if not self.initialize():
            print("Failed to initialize pygame UI. Exiting.")
            return

        self.running = True
        turn_counter = 0

        while self.running:
            # Handle automatic turns
            if auto_turns > 0 and turn_counter < auto_turns:
                self.simulation.run_turn()
                turn_counter += 1

            # Handle events
            self.running = self.handle_events()

            # Render
            self.render()

            # Cap at 60 FPS
            if self.clock:
                self.clock.tick(60)

        # Clean up
        pygame.quit()