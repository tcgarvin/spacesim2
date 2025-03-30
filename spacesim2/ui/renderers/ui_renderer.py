from typing import Dict, Tuple, Optional, List
import pygame
from pygame import Rect, Surface

class UIRenderer:
    """Renders common UI elements like panels, buttons, and dividers."""
    
    def __init__(self, screen: Surface, colors: Dict) -> None:
        """Initialize the UI renderer.
        
        Args:
            screen: Pygame screen surface to draw on
            colors: Color dictionary for styling
        """
        self.screen = screen
        self.colors = colors
        
    def draw_panel(self, rect: Rect, color: Optional[Tuple[int, int, int]] = None, 
                  border_radius: int = 0, border_width: int = 0) -> None:
        """Draw a panel with optional border radius and border.
        
        Args:
            rect: Rectangle dimensions
            color: Panel color (uses default panel color if None)
            border_radius: Rounded corner radius
            border_width: Border width (0 for filled panel)
        """
        if color is None:
            color = self.colors["ui_elements"]["panel"]
            
        pygame.draw.rect(
            self.screen,
            color,
            rect,
            border_width,
            border_radius=border_radius
        )
        
    def draw_button(self, rect: Rect, is_hover: bool = False, 
                   border_radius: int = 3) -> None:
        """Draw a button with hover effect.
        
        Args:
            rect: Button rectangle
            is_hover: Whether the button is being hovered over
            border_radius: Rounded corner radius
        """
        color = self.colors["ui_elements"]["button_hover"] if is_hover else self.colors["ui_elements"]["button"]
        
        pygame.draw.rect(
            self.screen,
            color,
            rect,
            border_radius=border_radius
        )
        
    def draw_divider(self, start_pos: Tuple[int, int], end_pos: Tuple[int, int], 
                    width: int = 1) -> None:
        """Draw a divider line.
        
        Args:
            start_pos: Starting position (x, y)
            end_pos: Ending position (x, y)
            width: Line width
        """
        pygame.draw.line(
            self.screen,
            self.colors["pane_divider"],
            start_pos,
            end_pos,
            width
        )
        
    def draw_pane_backgrounds(self, active_pane: int, pane_dimensions: Dict) -> None:
        """Draw the backgrounds for all panes, highlighting the active one.
        
        Args:
            active_pane: Index of the active pane (0, 1, or 2)
            pane_dimensions: Dictionary with pane dimensions
        """
        # Draw active pane background if valid
        if active_pane in self.colors["active_pane"]:
            if active_pane == 0:  # Left pane
                pygame.draw.rect(
                    self.screen, 
                    self.colors["active_pane"][0], 
                    (0, 0, pane_dimensions["left_width"], pane_dimensions["height"])
                )
            elif active_pane == 1:  # Center pane
                pygame.draw.rect(
                    self.screen, 
                    self.colors["active_pane"][1], 
                    (pane_dimensions["left_width"], 0, 
                     pane_dimensions["center_width"], pane_dimensions["height"])
                )
            elif active_pane == 2:  # Right pane
                pygame.draw.rect(
                    self.screen, 
                    self.colors["active_pane"][2], 
                    (pane_dimensions["left_width"] + pane_dimensions["center_width"], 0, 
                     pane_dimensions["right_width"], pane_dimensions["height"])
                )
                
        # Draw pane dividers
        pygame.draw.line(
            self.screen, 
            self.colors["pane_divider"], 
            (pane_dimensions["left_width"], 0), 
            (pane_dimensions["left_width"], pane_dimensions["height"]), 
            2
        )
        pygame.draw.line(
            self.screen, 
            self.colors["pane_divider"], 
            (pane_dimensions["left_width"] + pane_dimensions["center_width"], 0), 
            (pane_dimensions["left_width"] + pane_dimensions["center_width"], pane_dimensions["height"]), 
            2
        )