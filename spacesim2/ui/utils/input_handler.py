from typing import Callable, Dict, List, Optional, Tuple, Any, Union
import pygame
from pygame.event import Event

class InputHandler:
    """Handles user input events from pygame."""
    
    def __init__(self) -> None:
        """Initialize the input handler."""
        # Event callbacks
        self.key_callbacks: Dict[int, Callable[[Event], None]] = {}
        self.mouse_click_callbacks: Dict[int, Callable[[Event], None]] = {}
        self.mouse_scroll_callbacks: Dict[int, Callable[[Event], None]] = {}
        self.quit_callbacks: List[Callable[[], None]] = []
        
    def register_key_callback(self, key: int, callback: Callable[[Event], Optional[bool]]) -> None:
        """Register a callback for a specific key press.
        
        Args:
            key: pygame key constant (e.g. pygame.K_SPACE)
            callback: Function to call when key is pressed
                      If the callback returns False, handle_events will also return False
        """
        self.key_callbacks[key] = callback
        
    def register_mouse_click_callback(self, button: int, callback: Callable[[Event], None]) -> None:
        """Register a callback for mouse click.
        
        Args:
            button: Mouse button number (1-5)
            callback: Function to call when button is clicked
        """
        self.mouse_click_callbacks[button] = callback
        
    def register_mouse_scroll_callback(self, direction: int, callback: Callable[[Event], None]) -> None:
        """Register a callback for mouse scroll.
        
        Args:
            direction: 4 for scroll up, 5 for scroll down
            callback: Function to call when scrolling
        """
        self.mouse_scroll_callbacks[direction] = callback
        
    def register_quit_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback for quit events."""
        self.quit_callbacks.append(callback)
        
    def handle_events(self) -> bool:
        """Process all pending pygame events.
        
        Returns:
            False if the application should quit, True otherwise
        """
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                for callback in self.quit_callbacks:
                    callback()
                return False
                
            elif event.type == pygame.KEYDOWN:
                if event.key in self.key_callbacks:
                    # Call the callback and check if it returns False
                    result = self.key_callbacks[event.key](event)
                    if result is False:
                        return False
                    
            elif event.type == pygame.MOUSEBUTTONDOWN:
                # Handle click events
                if event.button in self.mouse_click_callbacks:
                    self.mouse_click_callbacks[event.button](event)
                    
                # Handle scroll events
                if event.button in self.mouse_scroll_callbacks:
                    self.mouse_scroll_callbacks[event.button](event)
                    
        return True