from typing import Dict, Tuple, Optional
import math
import pygame
from pygame.surface import Surface

from spacesim2.core.planet import Planet

class PlanetRenderer:
    """Renders planets and their positions."""
    
    def __init__(self, screen: Surface, colors: Dict) -> None:
        """Initialize the planet renderer.
        
        Args:
            screen: Pygame screen surface to draw on
            colors: Color dictionary for styling
        """
        self.screen = screen
        self.colors = colors
        self.planet_positions: Dict[Planet, Tuple[int, int]] = {}
        self.planet_colors: Dict[Planet, Tuple[int, int, int]] = {}
        self.planet_radius = 15  # Smaller radius for star-like appearance
        
    def generate_positions(self, planets: list, viewport_info: Dict) -> None:
        """Generate positions for planets based on a 0-100 coordinate system where (0,0) is top-left.
        
        Args:
            planets: List of planets to position
            viewport_info: Dictionary with viewport dimensions
        """
        if not planets:
            return
            
        # Clear existing positions
        self.planet_positions = {}
        
        # Unpack viewport parameters
        viewport_left = viewport_info['left']
        viewport_top = viewport_info['top']
        viewport_width = viewport_info['width']
        viewport_height = viewport_info['height']
        
        # For all planets, map from 0-100 range to screen coordinates
        for planet in planets:
            # Convert from 0-100 coordinate space to viewport screen space
            # x increases to the right, y increases downward
            screen_x = viewport_left + (planet.x / 100.0) * viewport_width
            screen_y = viewport_top + (planet.y / 100.0) * viewport_height
            
            self.planet_positions[planet] = (int(screen_x), int(screen_y))
    
    def set_planet_color(self, planet: Planet, color: Tuple[int, int, int]) -> None:
        """Set a specific color for a planet."""
        self.planet_colors[planet] = color
            
    def draw_star(self, x: int, y: int, color: Tuple[int, int, int], is_selected: bool) -> None:
        """Draw a 4-point star at the given coordinates with the given color."""
        # Adjust star size based on selection state
        inner_radius = self.planet_radius // 3
        if is_selected:
            outer_radius = self.planet_radius
        else:
            outer_radius = self.planet_radius - 2
        
        # Calculate the 8 points of the 4-point star
        points = []
        
        # 4 outer points
        for i in range(4):
            angle = math.pi / 2 * i
            point_x = x + int(outer_radius * math.cos(angle))
            point_y = y + int(outer_radius * math.sin(angle))
            points.append((point_x, point_y))
        
        # 4 inner points (at 45-degree angles from the outer points)
        for i in range(4):
            angle = math.pi / 2 * i + math.pi / 4
            point_x = x + int(inner_radius * math.cos(angle))
            point_y = y + int(inner_radius * math.sin(angle))
            points.append((point_x, point_y))
        
        # Reorder points to create a star pattern
        star_points = []
        for i in range(4):
            star_points.append(points[i])      # Outer point
            star_points.append(points[i+4])    # Inner point at 45 degrees
        
        # Draw the star
        pygame.draw.polygon(self.screen, color, star_points)
        
        # Draw center circle
        pygame.draw.circle(self.screen, color, (x, y), inner_radius // 2)
        
        # Draw a thin outline for better definition
        pygame.draw.polygon(self.screen, (min(255, color[0]+30), min(255, color[1]+30), min(255, color[2]+30)), star_points, 1)
        
    def draw_planet(self, planet: Planet, is_selected: bool = False) -> None:
        """Draw the planet at its position."""
        if planet not in self.planet_positions:
            return
            
        pos_x, pos_y = self.planet_positions[planet]
        
        # Get planet's color
        if planet in self.planet_colors:
            planet_color = self.planet_colors[planet]
        elif is_selected:
            planet_color = self.colors["planet"]["selected"]
        else:
            planet_color = self.colors["planet"]["default"]
            
        # Draw planet as a 4-point star
        self.draw_star(pos_x, pos_y, planet_color, is_selected)
        
        # For the selected planet, draw a selection indicator
        if is_selected:
            # Draw a pulsing selection ring
            pulse = (math.sin(pygame.time.get_ticks() * 0.005) + 1) * 0.5  # Value between 0 and 1
            ring_radius = int(self.planet_radius * 1.8 + pulse * 3)
            pygame.draw.circle(
                self.screen, 
                self.colors["planet"]["outline"], 
                (pos_x, pos_y), 
                ring_radius, 
                1
            )
        
        return pos_x, pos_y  # Return the position for other renderers to use