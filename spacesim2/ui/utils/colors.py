from typing import Dict, Tuple, Any
import random

# Color type
ColorType = Tuple[int, int, int]

class ColorManager:
    """Manages UI color schemes."""
    
    def __init__(self, seed: int = 42) -> None:
        """Initialize color manager with a random seed for consistent colors."""
        # Initialize random seed for consistent colors
        random.seed(seed)
        
        # Main UI colors
        self.colors: Dict[str, Any] = {
            "background": (10, 10, 20),
            "pane_divider": (50, 50, 70),
            "active_pane": {
                0: (20, 20, 40),  # Left pane when active
                1: (20, 30, 40),  # Center pane when active
                2: (30, 20, 40),  # Right pane when active
            },
            "text": {
                "normal": (200, 200, 200),
                "highlight": (255, 255, 255),
                "header": (180, 180, 255),
                "money": (150, 255, 150),
                "food": (255, 200, 100),
                "error": (255, 100, 100),
                "planet": (150, 200, 255),
                "market_maker": (220, 180, 50),
            },
            "planet": {
                "default": (0, 100, 200),
                "selected": (50, 150, 255),
                "outline": (100, 200, 255),
            },
            "actor": {
                "default": (200, 200, 200),
                "selected": (255, 255, 255),
                "market_maker": (220, 180, 50),
            },
            "ship": {
                "default": (180, 150, 255),
                "selected": (255, 200, 255),
                "in_transit": (150, 100, 200),
                "needs_maintenance": (255, 100, 100),
            },
            "ui_elements": {
                "button": (70, 70, 90),
                "button_hover": (90, 90, 120),
                "panel": (30, 30, 40),
            }
        }
        
        # Planet colors
        self.planet_colors = {}
        self._generate_planet_colors()
    
    def _generate_planet_colors(self) -> None:
        """Generate vibrant colors for planets."""
        # Predefined vibrant colors for small number of planets
        self.vibrant_colors = [
            (255, 130, 40),   # Orange
            (50, 180, 255),   # Bright blue
            (255, 60, 100),   # Pink
            (80, 220, 100),   # Green
            (220, 70, 220),   # Purple
            (230, 230, 30),   # Yellow
            (30, 210, 180),   # Teal
            (200, 180, 80),   # Gold
        ]
    
    def generate_planet_color(self, index: int) -> ColorType:
        """Generate a color for a planet based on its index."""
        if index < len(self.vibrant_colors):
            # Use predefined colors for first few planets
            return self.vibrant_colors[index]
        else:
            # Generate a random vibrant color
            # Ensure at least one channel is bright
            r = random.randint(50, 255)
            g = random.randint(50, 255)
            b = random.randint(50, 255)
            
            # Make sure at least one channel is > 200 for vibrancy
            brightest = max(r, g, b)
            if brightest < 200:
                if brightest == r:
                    r = random.randint(200, 255)
                elif brightest == g:
                    g = random.randint(200, 255)
                else:
                    b = random.randint(200, 255)
            
            return (r, g, b)