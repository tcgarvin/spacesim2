from typing import Dict, Tuple, Optional, List
import math
import pygame
from pygame.surface import Surface

from spacesim2.core.ship import Ship, ShipStatus
from spacesim2.core.planet import Planet

class ShipRenderer:
    """Renders ships in space and in orbit around planets."""
    
    def __init__(self, screen: Surface, colors: Dict, planet_positions: Dict[Planet, Tuple[int, int]]) -> None:
        """Initialize the ship renderer.
        
        Args:
            screen: Pygame screen surface to draw on
            colors: Color dictionary for styling
            planet_positions: Dictionary mapping planets to their screen positions
        """
        self.screen = screen
        self.colors = colors
        self.planet_positions = planet_positions
        self.ship_orbit_radius = 30  # Distance from planet center when in orbit
        self.ship_size = 5  # Size of ships on screen
        
    def update_planet_positions(self, planet_positions: Dict[Planet, Tuple[int, int]]) -> None:
        """Update the planet positions dictionary."""
        self.planet_positions = planet_positions
        
    def draw_ship(self, x: int, y: int, color: Tuple[int, int, int]) -> None:
        """Draw a ship at the given coordinates with the given color."""
        # Create a small diamond shape (rotated square)
        size = self.ship_size
        
        # Four points of a diamond
        diamond_points = [
            (x, y - size),       # Top
            (x + size, y),       # Right
            (x, y + size),       # Bottom
            (x - size, y)        # Left
        ]
        
        # Draw the diamond
        pygame.draw.polygon(self.screen, color, diamond_points)
        
        # Draw a thin outline for better definition
        pygame.draw.polygon(self.screen, (min(255, color[0]+30), min(255, color[1]+30), min(255, color[2]+30)), diamond_points, 1)
        
    def draw_ships_in_orbit(self, planet: Planet, ships: List[Ship], selected_ship: Optional[Ship] = None) -> None:
        """Draw ships in orbit around a planet.
        
        Args:
            planet: The planet the ships are orbiting
            ships: List of ships to draw
            selected_ship: Currently selected ship (if any)
        """
        if planet not in self.planet_positions or not ships:
            return
            
        # Filter only docked ships
        ships_in_orbit = [ship for ship in ships if ship.status == ShipStatus.DOCKED]
        if not ships_in_orbit:
            return
            
        # Get planet position
        planet_x, planet_y = self.planet_positions[planet]
        
        # Distribute ships evenly around the planet in a circle
        orbit_radius = self.ship_orbit_radius
        for i, ship in enumerate(ships_in_orbit):
            # Calculate angle based on ship index
            angle = 2 * math.pi * i / max(1, len(ships_in_orbit))
            ship_x = planet_x + int(orbit_radius * math.cos(angle))
            ship_y = planet_y + int(orbit_radius * math.sin(angle))
            
            # Draw the ship as a small diamond
            ship_color = self.colors["ship"]["selected"] if ship == selected_ship else self.colors["ship"]["default"]
            self.draw_ship(ship_x, ship_y, ship_color)
            
    def draw_ships_in_transit(self, ships: List[Ship], selected_ship: Optional[Ship] = None) -> None:
        """Draw ships that are traveling between planets.
        
        Args:
            ships: List of ships to check for transit
            selected_ship: Currently selected ship (if any)
        """
        # Filter ships that are actually in transit
        ships_in_transit = [ship for ship in ships 
                            if ship.status == ShipStatus.TRAVELING 
                            and ship.destination is not None
                            and ship.planet is not None]
        
        if not ships_in_transit:
            return
            
        for ship in ships_in_transit:
            # Get the coordinates for origin and destination planets
            origin_pos = self.planet_positions.get(ship.planet)
            dest_pos = self.planet_positions.get(ship.destination)
            
            if not origin_pos or not dest_pos:
                continue
                
            # Calculate the ship's current position based on travel progress
            progress = ship.travel_progress
            ship_x = int(origin_pos[0] + (dest_pos[0] - origin_pos[0]) * progress)
            ship_y = int(origin_pos[1] + (dest_pos[1] - origin_pos[1]) * progress)
            
            # Draw a line between the planets
            pygame.draw.line(
                self.screen,
                self.colors["ship"]["in_transit"],
                origin_pos,
                dest_pos,
                1
            )
            
            # Draw the ship
            ship_color = self.colors["ship"]["selected"] if ship == selected_ship else self.colors["ship"]["in_transit"]
            self.draw_ship(ship_x, ship_y, ship_color)
            
            return ship_x, ship_y  # Return position for text rendering