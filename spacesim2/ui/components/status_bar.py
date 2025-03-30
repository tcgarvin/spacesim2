from typing import Dict, List, Optional
import pygame
from pygame import Rect, Surface

from spacesim2.core.simulation import Simulation
from spacesim2.ui.utils.text import TextRenderer

class StatusBar:
    """Component for displaying the status bar at the bottom of the screen."""
    
    def __init__(self, screen: Surface, colors: Dict, width: int, height: int) -> None:
        """Initialize the status bar.
        
        Args:
            screen: Pygame surface to render on
            colors: Dictionary of UI colors
            width: Screen width
            height: Screen height
        """
        self.screen = screen
        self.colors = colors
        self.width = width
        self.height = height
        
        # Help text options
        self.help_text = [
            "Space: Advance turn", 
            "Tab: Switch panes",
            "Arrow keys: Navigate",
            "Enter: Select item",
            "S: Toggle Ships/Actors",
            "Esc: Quit",
        ]
        
        # Current state
        self.simulation: Optional[Simulation] = None
        
    def set_simulation(self, simulation: Simulation) -> None:
        """Set the simulation reference."""
        self.simulation = simulation
        
    def render(self, text_renderer: TextRenderer) -> None:
        """Render the status bar.
        
        Args:
            text_renderer: TextRenderer for rendering text
        """
        # Draw background
        status_bar_height = 40
        pygame.draw.rect(
            self.screen,
            self.colors["ui_elements"]["panel"],
            (0, self.height - status_bar_height, self.width, status_bar_height)
        )
        
        # Draw turn counter
        if self.simulation:
            turn_text, turn_rect = text_renderer.render_text(
                f"Turn: {self.simulation.current_turn}", "normal", self.colors["text"]["highlight"]
            )
            turn_rect.topleft = (20, self.height - status_bar_height + 10)
            self.screen.blit(turn_text, turn_rect)
        
        # Draw help text
        help_x = 200
        for help_item in self.help_text:
            help_text, help_rect = text_renderer.render_text(
                help_item, "small", self.colors["text"]["normal"]
            )
            help_rect.topleft = (help_x, self.height - status_bar_height + 13)
            self.screen.blit(help_text, help_rect)
            help_x += help_rect.width + 30