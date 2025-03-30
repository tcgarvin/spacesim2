from typing import Dict, List, Optional, Tuple
import pygame
from pygame import Rect, Surface

from spacesim2.core.ship import Ship, ShipStatus
from spacesim2.core.commodity import CommodityType
from spacesim2.core.planet import Planet
from spacesim2.ui.utils.text import TextRenderer

class ShipListPanel:
    """Component for displaying and interacting with a list of ships."""
    
    def __init__(self, screen: Surface, fonts: Dict, colors: Dict, width: int, height: int) -> None:
        """Initialize the ship list panel.
        
        Args:
            screen: Pygame surface to render on
            fonts: Dictionary of pygame font objects
            colors: Dictionary of UI colors
            width: Panel width
            height: Panel height
        """
        self.screen = screen
        self.fonts = fonts
        self.colors = colors
        self.width = width
        self.height = height
        
        # UI configuration
        self.item_height = 40
        self.scroll_offset = 0
        self.visible_items = 20
        
        # Current state
        self.selected_planet: Optional[Planet] = None
        self.selected_ship: Optional[Ship] = None
        
    def set_selected_planet(self, planet: Optional[Planet]) -> None:
        """Set the planet whose ships will be shown."""
        self.selected_planet = planet
        self.scroll_offset = 0  # Reset scroll position
        
    def set_selected_ship(self, ship: Optional[Ship]) -> None:
        """Set the currently selected ship."""
        self.selected_ship = ship
        
    def scroll_up(self, amount: int = 3) -> None:
        """Scroll the list up by the specified amount."""
        self.scroll_offset = max(0, self.scroll_offset - amount)
        
    def scroll_down(self, amount: int = 3) -> None:
        """Scroll the list down by the specified amount."""
        if not self.selected_planet or not self.selected_planet.ships:
            return
            
        max_offset = max(0, len(self.selected_planet.ships) - self.visible_items)
        self.scroll_offset = min(max_offset, self.scroll_offset + amount)
        
    def handle_click(self, x: int, y: int) -> bool:
        """Handle mouse click within the ship list.
        
        Args:
            x: Mouse x position
            y: Mouse y position
            
        Returns:
            Whether the click was handled by this component
        """
        if not self.selected_planet:
            return False
            
        # Calculate list boundaries
        list_start_y = 80  # Start position of the ship list
        
        # Check if click is in the ship list area
        if y >= list_start_y:
            # Calculate which ship was clicked
            relative_y = y - list_start_y
            index = self.scroll_offset + (relative_y // self.item_height)
            
            # Select the ship if valid
            if 0 <= index < len(self.selected_planet.ships):
                self.selected_ship = self.selected_planet.ships[index]
                return True
                
        return False
        
    def handle_key(self, key: int) -> bool:
        """Handle key press for ship list navigation.
        
        Args:
            key: Pygame key constant
            
        Returns:
            Whether the key was handled by this component
        """
        if not self.selected_planet or not self.selected_planet.ships:
            return False
            
        if key == pygame.K_UP:
            # Select previous ship or scroll up
            if self.selected_ship in self.selected_planet.ships:
                current_index = self.selected_planet.ships.index(self.selected_ship)
                if current_index > 0:
                    self.selected_ship = self.selected_planet.ships[current_index - 1]
                    # Adjust scroll if needed
                    if current_index - 1 < self.scroll_offset:
                        self.scroll_offset = current_index - 1
                    return True
            else:
                # No ship selected, select the last one
                self.selected_ship = self.selected_planet.ships[-1]
                return True
                
        elif key == pygame.K_DOWN:
            # Select next ship or scroll down
            if self.selected_ship in self.selected_planet.ships:
                current_index = self.selected_planet.ships.index(self.selected_ship)
                if current_index < len(self.selected_planet.ships) - 1:
                    self.selected_ship = self.selected_planet.ships[current_index + 1]
                    # Adjust scroll if needed
                    if current_index + 1 >= self.scroll_offset + self.visible_items:
                        self.scroll_offset = current_index + 1 - self.visible_items + 1
                    return True
            else:
                # No ship selected, select the first one
                self.selected_ship = self.selected_planet.ships[0]
                return True
                
        return False
    
    def render(self, text_renderer: TextRenderer) -> None:
        """Render the ship list panel.
        
        Args:
            text_renderer: TextRenderer for rendering text
        """
        # Title
        if self.selected_planet:
            title = f"Ships at {self.selected_planet.name}"
            item_count = len(self.selected_planet.ships) if self.selected_planet else 0
            subtitle = f"{item_count} ships"
        else:
            title = "No Planet Selected"
            subtitle = "0 ships"
            
        title_surface, title_rect = text_renderer.render_text(
            title, "large", self.colors["text"]["header"]
        )
        title_rect.topleft = (20, 20)
        self.screen.blit(title_surface, title_rect)
        
        # Subtitle with count
        subtitle_surface, subtitle_rect = text_renderer.render_text(
            subtitle, "normal", self.colors["text"]["normal"]
        )
        subtitle_rect.topleft = (20, 50)
        self.screen.blit(subtitle_surface, subtitle_rect)
        
        # Draw list header
        header_y = 80
        pygame.draw.line(
            self.screen, 
            self.colors["pane_divider"], 
            (10, header_y - 5), 
            (self.width - 10, header_y - 5), 
            1
        )
        
        # Draw scrollable ship list
        if not self.selected_planet or not self.selected_planet.ships:
            no_ships_text, no_ships_rect = text_renderer.render_text(
                "No ships available", "normal", self.colors["text"]["error"]
            )
            no_ships_rect.topleft = (20, header_y + 20)
            self.screen.blit(no_ships_text, no_ships_rect)
            return
            
        # Calculate visible range
        start_index = min(self.scroll_offset, len(self.selected_planet.ships) - 1) if self.selected_planet.ships else 0
        end_index = min(start_index + self.visible_items, len(self.selected_planet.ships)) if self.selected_planet.ships else 0
        
        # Draw each ship in the visible range
        for i in range(start_index, end_index):
            ship = self.selected_planet.ships[i]
            y_pos = header_y + ((i - start_index) * self.item_height)
            
            # Highlight if selected
            if ship == self.selected_ship:
                pygame.draw.rect(
                    self.screen,
                    self.colors["ui_elements"]["button_hover"],
                    (5, y_pos, self.width - 10, self.item_height - 2)
                )
            
            # Ship name and status
            name_color = self.colors["ship"]["default"]
            if ship.status == ShipStatus.TRAVELING:
                name_color = self.colors["ship"]["in_transit"]
            elif ship.status == ShipStatus.NEEDS_MAINTENANCE:
                name_color = self.colors["ship"]["needs_maintenance"]
                
            name_text, name_rect = text_renderer.render_text(f"{ship.name}", "normal", name_color)
            name_rect.topleft = (20, y_pos + 10)
            self.screen.blit(name_text, name_rect)
            
            # Ship money status
            money_text, money_rect = text_renderer.render_text(
                f"${ship.money:,}", "small", self.colors["text"]["money"]
            )
            money_rect.topright = (self.width - 20, y_pos + 5)
            self.screen.blit(money_text, money_rect)
            
            # Ship cargo status
            cargo_food = ship.cargo.get_quantity(CommodityType.RAW_FOOD)
            cargo_fuel = ship.cargo.get_quantity(CommodityType.FUEL)
            cargo_text, cargo_rect = text_renderer.render_text(
                f"Food: {cargo_food}, Fuel: {cargo_fuel}", "small", self.colors["text"]["food"]
            )
            cargo_rect.topright = (self.width - 20, y_pos + 22)
            self.screen.blit(cargo_text, cargo_rect)
        
        # Draw scroll indicators if needed
        if start_index > 0:
            # Up arrow
            pygame.draw.polygon(
                self.screen,
                self.colors["text"]["normal"],
                [(self.width - 30, header_y + 20), (self.width - 20, header_y + 5), (self.width - 10, header_y + 20)]
            )
            
        if end_index < len(self.selected_planet.ships):
            # Down arrow
            bottom_y = header_y + (self.visible_items * self.item_height) + 20
            pygame.draw.polygon(
                self.screen,
                self.colors["text"]["normal"],
                [(self.width - 30, bottom_y - 20), (self.width - 20, bottom_y - 5), (self.width - 10, bottom_y - 20)]
            )