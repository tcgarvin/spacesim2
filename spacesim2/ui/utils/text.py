from typing import Dict, Tuple, Optional
import pygame
from pygame.font import Font
from pygame.surface import Surface

class TextRenderer:
    """Handles text rendering with different fonts and styles."""
    
    def __init__(self) -> None:
        """Initialize the text renderer."""
        self.fonts: Dict[str, Font] = {}
        
    def initialize(self) -> None:
        """Initialize fonts (must be called after pygame.init())."""
        self.fonts = {
            "small": pygame.font.SysFont(None, 18),
            "normal": pygame.font.SysFont(None, 24),
            "large": pygame.font.SysFont(None, 32),
            "title": pygame.font.SysFont(None, 48),
        }
    
    def render_text(self, 
                   text: str, 
                   font_size: str = "normal", 
                   color: Tuple[int, int, int] = (255, 255, 255), 
                   center_pos: Optional[Tuple[int, int]] = None) -> Tuple[Surface, pygame.Rect]:
        """Render text with the specified font and color.
        
        Args:
            text: The text to render
            font_size: The font size ("small", "normal", "large", "title")
            color: RGB color tuple
            center_pos: If provided, the text rect will be centered at this position
            
        Returns:
            Tuple of (rendered text surface, rect)
        """
        if font_size not in self.fonts:
            font_size = "normal"
            
        text_surface = self.fonts[font_size].render(text, True, color)
        text_rect = text_surface.get_rect()
        
        if center_pos:
            text_rect.center = center_pos
            
        return text_surface, text_rect