from typing import Dict, List, Optional, Tuple
import math
import pygame
from pygame import Rect, Surface

from spacesim2.core.planet import Planet
from spacesim2.core.ship import Ship, ShipStatus
from spacesim2.ui.renderers.planet_renderer import PlanetRenderer
from spacesim2.ui.renderers.ship_renderer import ShipRenderer
from spacesim2.ui.utils.text import TextRenderer

class PlanetViewPanel:
    """Component for displaying the planetary system view."""
    
    def __init__(self, screen: Surface, colors: Dict, 
                 x: int, y: int, width: int, height: int) -> None:
        """Initialize the planet view panel.
        
        Args:
            screen: Pygame surface to render on
            colors: Dictionary of UI colors
            x: Panel x position
            y: Panel y position
            width: Panel width
            height: Panel height
        """
        self.screen = screen
        self.colors = colors
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        
        # Viewport settings
        self.margin = 60  # Margin from edges
        self.viewport_left = self.x + self.margin
        self.viewport_top = self.y + self.margin + 80  # Extra space at top for headers
        self.viewport_width = self.width - (self.margin * 2)
        self.viewport_height = self.height - self.viewport_top - self.margin
        
        # Initialize renderers
        self.planet_renderer = PlanetRenderer(screen, colors)
        self.ship_renderer = None  # Will be initialized after planet positions are known
        
        # Current state
        self.planets: List[Planet] = []
        self.selected_planet: Optional[Planet] = None
        self.selected_ship: Optional[Ship] = None
        
    def set_planets(self, planets: List[Planet]) -> None:
        """Set the list of planets to display."""
        self.planets = planets
        
        # Generate planet positions based on their coordinates
        viewport_info = {
            'left': self.viewport_left,
            'top': self.viewport_top,
            'width': self.viewport_width,
            'height': self.viewport_height
        }
        self.planet_renderer.generate_positions(planets, viewport_info)
        
        # Initialize ship renderer with planet positions
        self.ship_renderer = ShipRenderer(self.screen, self.colors, self.planet_renderer.planet_positions)
        
        # Assign colors to planets
        for i, planet in enumerate(planets):
            color = self.colors["planet"]["default"]
            self.planet_renderer.set_planet_color(planet, color)
        
    def set_selected_planet(self, planet: Optional[Planet]) -> None:
        """Set the currently selected planet."""
        self.selected_planet = planet
        
    def set_selected_ship(self, ship: Optional[Ship]) -> None:
        """Set the currently selected ship."""
        self.selected_ship = ship
        
    def handle_click(self, x: int, y: int) -> bool:
        """Handle mouse click within the planet view.
        
        Args:
            x: Mouse x position
            y: Mouse y position
            
        Returns:
            Whether the click was handled by this component
        """
        # Check if any planet was clicked
        for planet in self.planets:
            if planet in self.planet_renderer.planet_positions:
                planet_x, planet_y = self.planet_renderer.planet_positions[planet]
                
                # Calculate distance from click to planet center
                distance = math.sqrt((x - planet_x) ** 2 + (y - planet_y) ** 2)
                
                # For click detection, use a slightly larger radius than the visual star
                # This makes it easier to select small stars
                click_radius = self.planet_renderer.planet_radius * 1.5
                
                # If click is inside clickable area
                if distance <= click_radius:
                    self.selected_planet = planet
                    return True
                    
                # Also check if the planet's name was clicked (estimate position)
                name_rect = Rect(0, 0, 100, 20)  # Approximate text dimensions
                name_rect.center = (planet_x, planet_y + self.planet_renderer.planet_radius + 15)
                name_rect.inflate_ip(10, 6)  # Make clickable area slightly larger than text
                
                if name_rect.collidepoint(x, y):
                    self.selected_planet = planet
                    return True
                    
        return False
        
    def handle_key(self, key: int) -> bool:
        """Handle key press for planet view navigation.
        
        Args:
            key: Pygame key constant
            
        Returns:
            Whether the key was handled by this component
        """
        if not self.planets:
            return False
            
        # Basic navigation through planets
        current_index = self.planets.index(self.selected_planet) if self.selected_planet in self.planets else 0
        
        if key == pygame.K_UP or key == pygame.K_LEFT:
            # Move to previous planet
            if current_index > 0:
                self.selected_planet = self.planets[current_index - 1]
                return True
                
        elif key == pygame.K_DOWN or key == pygame.K_RIGHT:
            # Move to next planet
            if current_index < len(self.planets) - 1:
                self.selected_planet = self.planets[current_index + 1]
                return True
                
        return False
    
    def render(self, text_renderer: TextRenderer, simulation_ships: List[Ship]) -> None:
        """Render the planet view panel.
        
        Args:
            text_renderer: TextRenderer for rendering text
            simulation_ships: List of all ships in the simulation
        """
        # Title
        title_surface, title_rect = text_renderer.render_text(
            "Star System", "large", self.colors["text"]["header"]
        )
        title_rect.topleft = (self.x + 20, 20)
        self.screen.blit(title_surface, title_rect)
        
        # Subtitle with count
        planet_count = len(self.planets)
        subtitle = f"{planet_count} planets"
        ship_count = len(simulation_ships)
        if ship_count > 0:
            subtitle += f", {ship_count} ships"
            
        subtitle_surface, subtitle_rect = text_renderer.render_text(
            subtitle, "normal", self.colors["text"]["normal"]
        )
        subtitle_rect.topleft = (self.x + 20, 50)
        self.screen.blit(subtitle_surface, subtitle_rect)
        
        # No planets case
        if not self.planets:
            no_planets_text, no_planets_rect = text_renderer.render_text(
                "No planets in simulation", "normal", self.colors["text"]["error"]
            )
            no_planets_rect.center = (self.x + (self.width // 2), self.y + (self.height // 2))
            self.screen.blit(no_planets_text, no_planets_rect)
            return
        
        # Update ship renderer with latest planet positions
        if self.ship_renderer:
            self.ship_renderer.update_planet_positions(self.planet_renderer.planet_positions)
            
            # Draw ships in transit before drawing planets
            self.ship_renderer.draw_ships_in_transit(simulation_ships, self.selected_ship)
        
        # Draw each planet
        for planet in self.planets:
            # Draw the planet
            self.planet_renderer.draw_planet(planet, planet == self.selected_planet)
            
            # Draw planet name below
            if planet in self.planet_renderer.planet_positions:
                pos_x, pos_y = self.planet_renderer.planet_positions[planet]
                
                # Get color based on selection state
                if planet == self.selected_planet:
                    text_color = self.colors["planet"]["selected"]
                else:
                    text_color = self.colors["planet"]["default"]
                
                # Draw planet name
                name_surface, name_rect = text_renderer.render_text(
                    planet.name, "small", text_color, center_pos=(pos_x, pos_y + self.planet_renderer.planet_radius + 15)
                )
                self.screen.blit(name_surface, name_rect)
                
                # Draw ship count if any
                if planet.ships:
                    ship_count = len([s for s in planet.ships if s.status == ShipStatus.DOCKED])
                    if ship_count > 0:
                        ship_count_text, ship_count_rect = text_renderer.render_text(
                            f"{ship_count} ship{'s' if ship_count > 1 else ''}", 
                            "small", 
                            self.colors["ship"]["default"],
                            center_pos=(pos_x, pos_y + self.planet_renderer.planet_radius + 30)
                        )
                        self.screen.blit(ship_count_text, ship_count_rect)
                
                # Draw ships in orbit around this planet
                if self.ship_renderer and planet.ships:
                    self.ship_renderer.draw_ships_in_orbit(planet, planet.ships, self.selected_ship)