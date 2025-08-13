from typing import Dict, List, Optional, Tuple, Set, Union
import pygame
import math
from pygame import Rect, Surface

from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.commodity import CommodityDefinition, Inventory
from spacesim2.core.planet import Planet
from spacesim2.core.ship import Ship, ShipStatus
from spacesim2.ui.utils.text import TextRenderer

class ActorListPanel:
    """Component for displaying and interacting with a list of actors and ships in a grid layout."""
    
    def __init__(self, screen: Surface, fonts: Dict, colors: Dict, width: int, height: int) -> None:
        """Initialize the actor list panel.
        
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
        
        # Grid configuration
        self.grid_start_y = 80  # Start position of the actor grid
        self.actor_size = 45    # Size of each actor/ship square
        self.padding = 5        # Padding between grid items
        self.grid_padding = 10  # Padding around the grid
        
        # Calculate grid dimensions
        self.columns = max(1, (width - 2 * self.grid_padding) // (self.actor_size + self.padding))
        
        # Scroll state
        self.scroll_offset = 0  # In rows, not individual entities
        
        # Detail area
        self.detail_area_height = int(height * 0.6)  # 60% of panel height for details
        self.detail_area_start = height - self.detail_area_height
        
        # Current state
        self.selected_planet: Optional[Planet] = None
        self.selected_actor: Optional[Actor] = None
        self.selected_ship: Optional[Ship] = None
        self.hovered_actor: Optional[Union[Actor, Ship]] = None
        
        # Context state
        self.context = "default"  # Can be "default", "market", "process", etc.
        self.selected_commodity: Optional[CommodityDefinition] = None
        
    def set_context(self, context: str) -> None:
        """Set the current context for actor visualization."""
        self.context = context
        
    def set_market_context(self, commodity: Optional[CommodityDefinition]) -> None:
        """Set the market context with a selected commodity."""
        self.context = "market"
        self.selected_commodity = commodity
        
    def set_selected_planet(self, planet: Optional[Planet]) -> None:
        """Set the planet whose actors will be shown."""
        self.selected_planet = planet
        self.scroll_offset = 0  # Reset scroll position
        self.hovered_actor = None
        
    def set_selected_actor(self, actor: Optional[Actor]) -> None:
        """Set the currently selected actor."""
        self.selected_actor = actor
        
    def set_hovered_actor(self, entity: Optional[Union[Actor, Ship]]) -> None:
        """Set the currently hovered actor or ship."""
        self.hovered_actor = entity
        
    def set_selected_ship(self, ship: Optional[Ship]) -> None:
        """Set the currently selected ship."""
        self.selected_ship = ship
        if ship:
            self.selected_actor = None
        
    def scroll_up(self, amount: int = 1) -> None:
        """Scroll the grid up by the specified amount of rows."""
        self.scroll_offset = max(0, self.scroll_offset - amount)
        
    def scroll_down(self, amount: int = 1) -> None:
        """Scroll the grid down by the specified amount of rows."""
        if not self.selected_planet:
            return
            
        # Get combined list of actors and ships
        all_entities = self.selected_planet.actors + self.selected_planet.ships
        if not all_entities:
            return
            
        total_entities = len(all_entities)
        total_rows = math.ceil(total_entities / self.columns)
        
        # Calculate how many rows are visible
        grid_height = self.detail_area_start - self.grid_start_y - self.grid_padding
        visible_rows = max(1, grid_height // (self.actor_size + self.padding))
        
        # Calculate maximum scroll offset
        max_offset = max(0, total_rows - visible_rows)
        self.scroll_offset = min(max_offset, self.scroll_offset + amount)
        
    def handle_mouse_motion(self, x: int, y: int) -> bool:
        """Handle mouse movement to track hovering.
        
        Args:
            x: Mouse x position
            y: Mouse y position
            
        Returns:
            Whether the motion was handled by this component
        """
        if not self.selected_planet:
            self.hovered_actor = None
            return False
            
        # Get combined list of actors and ships
        all_entities = self.selected_planet.actors + self.selected_planet.ships
        if not all_entities:
            self.hovered_actor = None
            return False
            
        # Check if mouse is in the grid area
        if (x < self.grid_padding or x > self.width - self.grid_padding or 
            y < self.grid_start_y or y > self.detail_area_start - self.grid_padding):
            self.hovered_actor = None
            return False
            
        # Calculate grid cell from coordinates
        grid_x = (x - self.grid_padding) // (self.actor_size + self.padding)
        grid_y = (y - self.grid_start_y) // (self.actor_size + self.padding)
        
        if grid_x < 0 or grid_x >= self.columns:
            self.hovered_actor = None
            return False
            
        # Calculate entity index
        entity_index = (self.scroll_offset + grid_y) * self.columns + grid_x
        
        if 0 <= entity_index < len(all_entities):
            self.hovered_actor = all_entities[entity_index]
            return True
        else:
            self.hovered_actor = None
            return False
            
    def handle_click(self, x: int, y: int) -> bool:
        """Handle mouse click within the actor/ship grid.
        
        Args:
            x: Mouse x position
            y: Mouse y position
            
        Returns:
            Whether the click was handled by this component
        """
        if not self.selected_planet:
            return False
            
        # Get combined list of actors and ships
        all_entities = self.selected_planet.actors + self.selected_planet.ships
        if not all_entities:
            return False
            
        # Check if click is in the grid area
        if (x < self.grid_padding or x > self.width - self.grid_padding or 
            y < self.grid_start_y or y > self.detail_area_start - self.grid_padding):
            return False
            
        # Calculate grid cell from coordinates
        grid_x = (x - self.grid_padding) // (self.actor_size + self.padding)
        grid_y = (y - self.grid_start_y) // (self.actor_size + self.padding)
        
        if grid_x < 0 or grid_x >= self.columns:
            return False
            
        # Calculate entity index
        entity_index = (self.scroll_offset + grid_y) * self.columns + grid_x
        
        if 0 <= entity_index < len(all_entities):
            # Get the clicked entity
            entity = all_entities[entity_index]
            
            # Handle selection based on entity type
            if isinstance(entity, Ship):
                # Select or deselect the ship
                if self.selected_ship == entity:
                    self.selected_ship = None
                else:
                    self.selected_ship = entity
                    self.selected_actor = None
            else:
                # Select or deselect the actor
                if self.selected_actor == entity:
                    self.selected_actor = None
                else:
                    self.selected_actor = entity
                    self.selected_ship = None
            return True
            
        return False
        
    def handle_key(self, key: int) -> bool:
        """Handle key press for actor/ship grid navigation.
        
        Args:
            key: Pygame key constant
            
        Returns:
            Whether the key was handled by this component
        """
        if not self.selected_planet:
            return False
            
        # Get combined list of actors and ships
        all_entities = self.selected_planet.actors + self.selected_planet.ships
        if not all_entities:
            return False
            
        # Get current index of selected entity
        current_index = -1
        if self.selected_actor in all_entities:
            current_index = all_entities.index(self.selected_actor)
        elif self.selected_ship in all_entities:
            current_index = all_entities.index(self.selected_ship)
        
        # Calculate total entities and rows/columns
        total_entities = len(all_entities)
        total_rows = math.ceil(total_entities / self.columns)
        
        if key == pygame.K_UP:
            if current_index >= 0:
                # Move selection up one row
                if current_index >= self.columns:
                    new_index = current_index - self.columns
                    new_entity = all_entities[new_index]
                    
                    # Set the appropriate selection based on entity type
                    if isinstance(new_entity, Ship):
                        self.selected_ship = new_entity
                        self.selected_actor = None
                    else:
                        self.selected_actor = new_entity
                        self.selected_ship = None
                    
                    # Adjust scroll if needed
                    row = new_index // self.columns
                    if row < self.scroll_offset:
                        self.scroll_offset = row
                    return True
            elif total_entities > 0:
                # No entity selected, select the last one
                new_entity = all_entities[-1]
                if isinstance(new_entity, Ship):
                    self.selected_ship = new_entity
                    self.selected_actor = None
                else:
                    self.selected_actor = new_entity
                    self.selected_ship = None
                
                # Adjust scroll to show the last row
                row = (total_entities - 1) // self.columns
                
                # Calculate how many rows are visible
                grid_height = self.detail_area_start - self.grid_start_y - self.grid_padding
                visible_rows = max(1, grid_height // (self.actor_size + self.padding))
                
                if row >= self.scroll_offset + visible_rows:
                    self.scroll_offset = max(0, row - visible_rows + 1)
                return True
                
        elif key == pygame.K_DOWN:
            if current_index >= 0:
                # Move selection down one row
                new_index = current_index + self.columns
                if new_index < total_entities:
                    new_entity = all_entities[new_index]
                    
                    # Set the appropriate selection based on entity type
                    if isinstance(new_entity, Ship):
                        self.selected_ship = new_entity
                        self.selected_actor = None
                    else:
                        self.selected_actor = new_entity
                        self.selected_ship = None
                    
                    # Adjust scroll if needed
                    row = new_index // self.columns
                    
                    # Calculate how many rows are visible
                    grid_height = self.detail_area_start - self.grid_start_y - self.grid_padding
                    visible_rows = max(1, grid_height // (self.actor_size + self.padding))
                    
                    if row >= self.scroll_offset + visible_rows:
                        self.scroll_offset = row - visible_rows + 1
                    return True
            elif total_entities > 0:
                # No entity selected, select the first one
                new_entity = all_entities[0]
                if isinstance(new_entity, Ship):
                    self.selected_ship = new_entity
                    self.selected_actor = None
                else:
                    self.selected_actor = new_entity
                    self.selected_ship = None
                
                # Ensure first row is visible
                self.scroll_offset = 0
                return True
                
        elif key == pygame.K_LEFT:
            if current_index > 0:
                # Move selection left
                new_entity = all_entities[current_index - 1]
                if isinstance(new_entity, Ship):
                    self.selected_ship = new_entity
                    self.selected_actor = None
                else:
                    self.selected_actor = new_entity
                    self.selected_ship = None
                return True
            elif current_index == 0 and total_entities > 0:
                # Wrap to end
                new_entity = all_entities[-1]
                if isinstance(new_entity, Ship):
                    self.selected_ship = new_entity
                    self.selected_actor = None
                else:
                    self.selected_actor = new_entity
                    self.selected_ship = None
                
                # Adjust scroll to show the last row
                row = (total_entities - 1) // self.columns
                
                # Calculate how many rows are visible
                grid_height = self.detail_area_start - self.grid_start_y - self.grid_padding
                visible_rows = max(1, grid_height // (self.actor_size + self.padding))
                
                if row >= self.scroll_offset + visible_rows:
                    self.scroll_offset = max(0, row - visible_rows + 1)
                return True
                
        elif key == pygame.K_RIGHT:
            if current_index >= 0 and current_index < total_entities - 1:
                # Move selection right
                new_entity = all_entities[current_index + 1]
                if isinstance(new_entity, Ship):
                    self.selected_ship = new_entity
                    self.selected_actor = None
                else:
                    self.selected_actor = new_entity
                    self.selected_ship = None
                return True
            elif current_index == total_entities - 1 and total_entities > 0:
                # Wrap to beginning
                new_entity = all_entities[0]
                if isinstance(new_entity, Ship):
                    self.selected_ship = new_entity
                    self.selected_actor = None
                else:
                    self.selected_actor = new_entity
                    self.selected_ship = None
                
                # Ensure first row is visible
                self.scroll_offset = 0
                return True
                
        return False
    
    def render(self, text_renderer: TextRenderer) -> None:
        """Render the actor/ship grid panel with detail area.
        
        Args:
            text_renderer: TextRenderer for rendering text
        """
        # Title
        if self.selected_planet:
            title = f"Entities on {self.selected_planet.name}"
            actor_count = len(self.selected_planet.actors) if self.selected_planet else 0
            ship_count = len(self.selected_planet.ships) if self.selected_planet else 0
            subtitle = f"{actor_count} actors, {ship_count} ships"
        else:
            title = "No Planet Selected"
            subtitle = "0 entities"
            
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
        
        # Draw header divider
        pygame.draw.line(
            self.screen, 
            self.colors["pane_divider"], 
            (10, self.grid_start_y - 5), 
            (self.width - 10, self.grid_start_y - 5), 
            1
        )
        
        # If no planet or entities, show message and return
        if not self.selected_planet or (not self.selected_planet.actors and not self.selected_planet.ships):
            no_entities_text, no_entities_rect = text_renderer.render_text(
                "No entities available", "normal", self.colors["text"]["error"]
            )
            no_entities_rect.topleft = (20, self.grid_start_y + 20)
            self.screen.blit(no_entities_text, no_entities_rect)
            return
            
        # Render entity grid
        self._render_actor_grid(text_renderer)
        
        # Draw divider between grid and detail area
        pygame.draw.line(
            self.screen, 
            self.colors["pane_divider"], 
            (10, self.detail_area_start - 5), 
            (self.width - 10, self.detail_area_start - 5), 
            1
        )
        
        # Render detail area
        self._render_detail_area(text_renderer)
    
    def _render_actor_grid(self, text_renderer: TextRenderer) -> None:
        """Render the grid of actor squares and ship circles."""
        if not self.selected_planet:
            return
            
        # Get combined list of actors and ships
        all_entities = self.selected_planet.actors + self.selected_planet.ships
        if not all_entities:
            return
            
        total_entities = len(all_entities)
        
        # Calculate grid dimensions
        total_rows = math.ceil(total_entities / self.columns)
        
        # Calculate how many rows are visible
        grid_height = self.detail_area_start - self.grid_start_y - self.grid_padding
        visible_rows = max(1, grid_height // (self.actor_size + self.padding))
        
        # Calculate visible entity range
        start_row = min(self.scroll_offset, total_rows - 1) if total_rows > 0 else 0
        end_row = min(start_row + visible_rows, total_rows)
        
        # Render visible entities in grid
        for row in range(start_row, end_row):
            for col in range(self.columns):
                entity_index = row * self.columns + col
                
                if entity_index < total_entities:
                    entity = all_entities[entity_index]
                    
                    # Calculate position
                    x = self.grid_padding + col * (self.actor_size + self.padding)
                    y = self.grid_start_y + (row - start_row) * (self.actor_size + self.padding)
                    
                    # Render appropriate shape based on entity type
                    if isinstance(entity, Ship):
                        self._render_ship_circle(entity, x, y, text_renderer)
                    else:
                        self._render_actor_square(entity, x, y, text_renderer)
        
        # Draw scroll indicators if needed
        if start_row > 0:
            # Up arrow
            pygame.draw.polygon(
                self.screen,
                self.colors["text"]["normal"],
                [(self.width - 30, self.grid_start_y + 10), 
                 (self.width - 20, self.grid_start_y), 
                 (self.width - 10, self.grid_start_y + 10)]
            )
            
        if end_row < total_rows:
            # Down arrow
            bottom_y = self.detail_area_start - 10
            pygame.draw.polygon(
                self.screen,
                self.colors["text"]["normal"],
                [(self.width - 30, bottom_y), 
                 (self.width - 20, bottom_y + 10), 
                 (self.width - 10, bottom_y)]
            )
    
    def _render_actor_square(self, actor: Actor, x: int, y: int, text_renderer: TextRenderer) -> None:
        """Render a single actor square in the grid."""
        
        # Determine base color based on actor type
        if actor.actor_type == ActorType.MARKET_MAKER:
            base_color = self.colors["actor"]["market_maker"]
        else:
            base_color = self.colors["actor"]["default"]
        
        # Enhanced market context coloring based on actor type and active orders
        if self.context == "market":
            # Market makers get a distinct color
            # Get active orders directly from the actor's active_orders dictionary
            has_buy_order = False
            has_sell_order = False
            has_recent_buy = False
            has_recent_sell = False
            
            # Check active orders dictionary directly
            for order_desc in actor.active_orders.values():
                if self.selected_commodity and self.selected_commodity.id in order_desc:
                    if "buy" in order_desc:
                        has_buy_order = True
                    elif "sell" in order_desc:
                        has_sell_order = True
                        
            # Check market history for recent transactions (last 2 turns)
            if self.selected_commodity:
                current_turn = actor.sim.current_turn
                for transaction in reversed(actor.market_history):
                    if current_turn - transaction['turn'] > 0:
                        break
                        
                    if transaction['commodity'] == self.selected_commodity.id:
                        if transaction['side'] == 'buy':
                            has_recent_buy = True
                        elif transaction['side'] == 'sell':
                            has_recent_sell = True
            
            # Determine color based on order presence and recent transactions
            if has_buy_order and has_sell_order:
                # Both buy and sell orders
                base_color = (200, 150, 220)  # Purple-gold blend
            elif has_buy_order:
                # Buy orders only - green
                base_color = (100, 200, 100)  # Green
            elif has_sell_order:
                # Sell orders only - red
                base_color = (200, 100, 100)  # Red
            elif has_recent_buy and has_recent_sell:
                # Recent transactions of both types
                base_color = (180, 140, 200)  # Lighter purple-gold
            elif has_recent_buy:
                # Recent buys only - deep green
                base_color = (0, 180, 0)  # Deep green
            elif has_recent_sell:
                # Recent sells only - deep red
                base_color = (180, 0, 0)  # Deep red
            else:
                # No orders or recent transactions - darker version of default
                base_color = (max(base_color[0] - 30, 0), 
                            max(base_color[1] - 30, 0), 
                            max(base_color[2] - 30, 0))
        
        # Draw the actor shape based on type
        if actor.actor_type == ActorType.MARKET_MAKER:
            # Draw diamond shape for market makers
            center_x = x + self.actor_size // 2
            center_y = y + self.actor_size // 2
            half_size = self.actor_size // 2
            
            # Define diamond points (top, right, bottom, left)
            diamond_points = [
                (center_x, center_y - half_size),  # top
                (center_x + half_size, center_y),  # right
                (center_x, center_y + half_size),  # bottom
                (center_x - half_size, center_y),  # left
            ]
            
            pygame.draw.polygon(
                self.screen,
                base_color,
                diamond_points
            )
            
            # Draw selection or hover highlight
            if actor == self.selected_actor:
                pygame.draw.polygon(
                    self.screen,
                    self.colors["text"]["highlight"],
                    diamond_points,
                    width=2
                )
            elif actor == self.hovered_actor:
                pygame.draw.polygon(
                    self.screen,
                    (180, 180, 180),  # Light gray
                    diamond_points,
                    width=1
                )
        else:
            # Draw square for regular actors
            pygame.draw.rect(
                self.screen,
                base_color,
                (x, y, self.actor_size, self.actor_size),
                border_radius=3
            )
            
            # Draw selection or hover highlight
            if actor == self.selected_actor:
                pygame.draw.rect(
                    self.screen,
                    self.colors["text"]["highlight"],
                    (x, y, self.actor_size, self.actor_size),
                    width=2,
                    border_radius=3
                )
            elif actor == self.hovered_actor:
                pygame.draw.rect(
                    self.screen,
                    (180, 180, 180),  # Light gray
                    (x, y, self.actor_size, self.actor_size),
                    width=1,
                    border_radius=3
                )
        
        # In market context, display commodity count for the selected commodity
        if self.context == "market" and self.selected_commodity:
            # Get the actual quantity of the selected commodity
            quantity = 0
            for commodity in actor.inventory.commodities:
                    if commodity.id == self.selected_commodity.id:
                        quantity = actor.inventory.get_quantity(commodity)
                        break
            
            # Only show count if non-zero
            if quantity > 0:
                # Render the quantity with black text for visibility
                count_text, count_rect = text_renderer.render_text(
                    str(quantity), "small", (0, 0, 0)  # Black text for visibility
                )
                
                # Position text in center of shape
                if actor.actor_type == ActorType.MARKET_MAKER:
                    # Center in diamond
                    count_rect.center = (center_x, center_y)
                else:
                    # Center in square
                    count_rect.center = (x + self.actor_size // 2, y + self.actor_size // 2)
                    
                self.screen.blit(count_text, count_rect)
    
    def _draw_actor_status_indicators(self, actor: Actor, x: int, y: int) -> None:
        """Draw small status indicators in the corners of the actor square."""
        # Top-left: Food status
        food_status = actor.food_consumed_this_turn
        food_color = self.colors["text"]["food"] if food_status else (150, 50, 50)  # Green if fed, red if hungry
        pygame.draw.circle(
            self.screen,
            food_color,
            (x + 5, y + 5),
            3
        )
        
        # Top-right: Market activity (e.g., has active orders)
        has_orders = len(actor.active_orders) > 0
        order_color = (50, 200, 50) if has_orders else (100, 100, 100)  # Green if has orders
        pygame.draw.circle(
            self.screen,
            order_color,
            (x + self.actor_size - 5, y + 5),
            3
        )
        
        # Bottom-left: Money status (arbitrary thresholds)
        if actor.money > 100:
            money_color = (50, 200, 50)  # Green if wealthy
        elif actor.money > 20:
            money_color = (200, 200, 50)  # Yellow if moderate
        else:
            money_color = (200, 50, 50)  # Red if poor
            
        pygame.draw.circle(
            self.screen,
            money_color,
            (x + 5, y + self.actor_size - 5),
            3
        )
        
        # Bottom-right: Activity status (from last_action)
        if actor.last_action:
            if "Failed" in actor.last_action:
                activity_color = (200, 50, 50)  # Red if failed
            elif "Government work" in actor.last_action:
                activity_color = (100, 100, 200)  # Blue for government work
            elif "Executed process" in actor.last_action:
                activity_color = (50, 200, 50)  # Green for successful process
            else:
                activity_color = (150, 150, 150)  # Gray for other/unknown
        else:
            activity_color = (150, 150, 150)
            
        pygame.draw.circle(
            self.screen,
            activity_color,
            (x + self.actor_size - 5, y + self.actor_size - 5),
            3
        )
    
    def _render_ship_circle(self, ship: Ship, x: int, y: int, text_renderer: TextRenderer) -> None:
        """Render a single ship circle in the grid."""
        
        # Determine base color based on ship status
        if ship.status == ShipStatus.TRAVELING:
            base_color = self.colors["ship"]["in_transit"]
        elif ship.status == ShipStatus.NEEDS_MAINTENANCE:
            base_color = self.colors["ship"]["needs_maintenance"]
        else:
            base_color = self.colors["ship"]["default"]
        
        # Enhanced market context coloring
        if self.context == "market":
            # Check active orders dictionary
            has_buy_order = False
            has_sell_order = False
            has_recent_buy = False
            has_recent_sell = False
            
            # Check active orders dictionary directly
            for order_desc in ship.active_orders.values():
                if self.selected_commodity and self.selected_commodity.id in order_desc:
                    if "buy" in order_desc:
                        has_buy_order = True
                    elif "sell" in order_desc:
                        has_sell_order = True
                        
            # Check market history for recent transactions (last 2 turns)
            if self.selected_commodity:
                current_turn = ship.simulation.current_turn if ship.simulation else 0
                for transaction in reversed(ship.market_history):
                    if current_turn - transaction['turn'] > 0:
                        break
                        
                    if transaction['commodity'] == self.selected_commodity.id:
                        if transaction['side'] == 'buy':
                            has_recent_buy = True
                        elif transaction['side'] == 'sell':
                            has_recent_sell = True
            
            # Determine color based on order presence and recent transactions
            if has_buy_order and has_sell_order:
                # Both buy and sell orders
                base_color = (200, 150, 220)  # Purple-gold blend
            elif has_buy_order:
                # Buy orders only - green
                base_color = (100, 200, 100)  # Green
            elif has_sell_order:
                # Sell orders only - red
                base_color = (200, 100, 100)  # Red
            elif has_recent_buy and has_recent_sell:
                # Recent transactions of both types
                base_color = (180, 140, 200)  # Lighter purple-gold
            elif has_recent_buy:
                # Recent buys only - deep green
                base_color = (0, 180, 0)  # Deep green
            elif has_recent_sell:
                # Recent sells only - deep red
                base_color = (180, 0, 0)  # Deep red
        
        # Calculate center and radius
        center_x = x + self.actor_size // 2
        center_y = y + self.actor_size // 2
        radius = self.actor_size // 2 - 2  # Slightly smaller than the square
        
        # Draw the ship circle
        pygame.draw.circle(
            self.screen,
            base_color,
            (center_x, center_y),
            radius
        )
        
        # Draw selection or hover highlight
        if ship == self.selected_ship:
            pygame.draw.circle(
                self.screen,
                self.colors["text"]["highlight"],
                (center_x, center_y),
                radius,
                width=2
            )
        elif ship == self.hovered_actor:
            pygame.draw.circle(
                self.screen,
                (180, 180, 180),  # Light gray
                (center_x, center_y),
                radius,
                width=1
            )
        
        # In market context, display commodity count for the selected commodity
        if self.context == "market" and self.selected_commodity:
            # Get the actual quantity of the selected commodity
            quantity = 0
            for commodity in ship.cargo.commodities:
                    if commodity.id == self.selected_commodity.id:
                        quantity = ship.cargo.get_quantity(commodity)
                        break
            
            # Only show count if non-zero
            if quantity > 0:
                # Render the quantity with black text for visibility
                count_text, count_rect = text_renderer.render_text(
                    str(quantity), "small", (0, 0, 0)  # Black text for visibility
                )
                
                # Center text in circle
                count_rect.center = (center_x, center_y)
                self.screen.blit(count_text, count_rect)
    
    def _render_detail_area(self, text_renderer: TextRenderer) -> None:
        """Render the detail area showing information about the selected or hovered entity."""
        # Display information about hovered entity (if any), otherwise the selected entity
        display_entity = self.hovered_actor if self.hovered_actor else (self.selected_actor if self.selected_actor else self.selected_ship)
        
        if not display_entity:
            # No entity to display, show a message
            info_text, info_rect = text_renderer.render_text(
                "Hover or select an entity to see details", "normal", self.colors["text"]["normal"]
            )
            info_rect.center = (self.width // 2, self.detail_area_start + self.detail_area_height // 2)
            self.screen.blit(info_text, info_rect)
            return
        
        # Start position for details
        x = 20
        y = self.detail_area_start + 15
        line_height = 24
        
        # Determine if it's a ship or actor
        if isinstance(display_entity, Ship):
            # Ship name and status
            status_color = self.colors["ship"]["default"]
            if display_entity.status == ShipStatus.TRAVELING:
                status_color = self.colors["ship"]["in_transit"]
            elif display_entity.status == ShipStatus.NEEDS_MAINTENANCE:
                status_color = self.colors["ship"]["needs_maintenance"]
                
            name_text, name_rect = text_renderer.render_text(
                f"{display_entity.name} (Ship - {display_entity.status.value})", "normal", status_color
            )
            name_rect.topleft = (x, y)
            self.screen.blit(name_text, name_rect)
            y += line_height
            
            # Location or travel status
            if display_entity.status == ShipStatus.TRAVELING:
                location_text, location_rect = text_renderer.render_text(
                    f"Traveling: {display_entity.planet.name} → {display_entity.destination.name} ({int(display_entity.travel_progress * 100)}%)", 
                    "normal", 
                    self.colors["text"]["normal"]
                )
            else:
                location_text, location_rect = text_renderer.render_text(
                    f"Docked at: {display_entity.planet.name if display_entity.planet else 'Unknown'}", 
                    "normal", 
                    self.colors["text"]["normal"]
                )
            location_rect.topleft = (x, y)
            self.screen.blit(location_text, location_rect)
            y += line_height
            
            # Money
            money_text, money_rect = text_renderer.render_text(
                f"Money: ${display_entity.money:,}", "normal", self.colors["text"]["money"]
            )
            money_rect.topleft = (x, y)
            self.screen.blit(money_text, money_rect)
            y += line_height
            
            # Cargo capacity
            cargo_used = display_entity.cargo.get_total_quantity()
            capacity_text, capacity_rect = text_renderer.render_text(
                f"Cargo: {cargo_used}/{display_entity.cargo_capacity} units", 
                "normal", 
                self.colors["text"]["normal"]
            )
            capacity_rect.topleft = (x, y)
            self.screen.blit(capacity_text, capacity_rect)
            y += line_height
            
        else:
            # Actor name and type
            name_color = self.colors["text"]["market_maker"] if display_entity.actor_type == ActorType.MARKET_MAKER else self.colors["text"]["header"]
            name_text, name_rect = text_renderer.render_text(
                f"{display_entity.name} ({display_entity.actor_type.value})", "normal", name_color
            )
            name_rect.topleft = (x, y)
            self.screen.blit(name_text, name_rect)
            y += line_height
            
            # Money
            money_text, money_rect = text_renderer.render_text(
                f"Money: ${display_entity.money:,}", "normal", self.colors["text"]["money"]
            )
            money_rect.topleft = (x, y)
            self.screen.blit(money_text, money_rect)
            y += line_height
            
            # Food status
            raw_food = None
            for commodity in display_entity.inventory.commodities:
                if commodity.id == "raw_food":
                    raw_food = commodity
                    break
                    
            food_qty = display_entity.inventory.get_quantity(raw_food) if raw_food else 0
            if food_qty > 0:
                food_status = "✓" if display_entity.food_consumed_this_turn else "✗"
                food_text, food_rect = text_renderer.render_text(
                    f"Food: {food_qty} {food_status}", "normal", self.colors["text"]["food"]
                )
                food_rect.topleft = (x, y)
                self.screen.blit(food_text, food_rect)
                y += line_height
        
        # Skills section (only show skills with significant deviation) - actors only
        if not isinstance(display_entity, Ship) and display_entity.skills:
            # Filter to only skills with significant deviation
            significant_skills = {
                skill_id: rating for skill_id, rating in display_entity.skills.items()
                if rating > 1.2 or rating < 0.8
            }
            
            if significant_skills:
                y += line_height // 2
                skills_title, skills_title_rect = text_renderer.render_text(
                    "Notable Skills:", "normal", self.colors["text"]["header"]
                )
                skills_title_rect.topleft = (x, y)
                self.screen.blit(skills_title, skills_title_rect)
                y += line_height
                
                # Show skills with percentage difference from baseline (1.0)
                for skill_id, rating in significant_skills.items():
                    skill_name = skill_id.replace("_", " ").title()
                    percent_diff = int((rating - 1.0) * 100)
                    percentage_str = f"+{percent_diff}%" if percent_diff > 0 else f"{percent_diff}%"
                    
                    # Color code: green for high values, orange/red for low values
                    if rating > 1.0:
                        # Bright green for high skills
                        text_color = (50, 200, 50)
                    else:
                        # Deep orange for low skills
                        text_color = (220, 120, 20)
                    
                    skill_text, skill_rect = text_renderer.render_text(
                        f"{skill_name}: {percentage_str}", "normal", text_color
                    )
                    skill_rect.topleft = (x + 10, y)
                    self.screen.blit(skill_text, skill_rect)
                    y += line_height
        
        # Inventory/cargo section
        has_items = False
        inventory = display_entity.cargo if isinstance(display_entity, Ship) else display_entity.inventory
        
        for commodity in inventory.commodities:
            quantity = inventory.get_quantity(commodity)
            if quantity > 0:
                has_items = True
                break
                
        if has_items:
            y += line_height // 2
            inventory_title, inventory_title_rect = text_renderer.render_text(
                "Cargo:" if isinstance(display_entity, Ship) else "Inventory:", 
                "normal", 
                self.colors["text"]["header"]
            )
            inventory_title_rect.topleft = (x, y)
            self.screen.blit(inventory_title, inventory_title_rect)
            y += line_height
            
            # Show all non-zero items
            column_width = self.width // 2 - 30
            current_x = x + 10
            current_y = y
            item_count = 0
            
            for commodity in inventory.commodities:
                quantity = inventory.get_quantity(commodity)
                if quantity > 0:
                    item_text, item_rect = text_renderer.render_text(
                        f"{commodity.name}: {quantity}", "normal", self.colors["text"]["normal"]
                    )
                    item_rect.topleft = (current_x, current_y)
                    self.screen.blit(item_text, item_rect)
                    
                    item_count += 1
                    if item_count % 2 == 0:
                        # Move to next row
                        current_y += line_height
                        current_x = x + 10
                    else:
                        # Move to second column
                        current_x = x + column_width
            
            # Update y position based on inventory items
            y = current_y + (line_height if item_count % 2 != 0 else 0)
        
        # Last actions section
        y += line_height // 2
        actions_title, actions_title_rect = text_renderer.render_text(
            "Recent Actions:", "normal", self.colors["text"]["header"]
        )
        actions_title_rect.topleft = (x, y)
        self.screen.blit(actions_title, actions_title_rect)
        y += line_height
        
        # Display last action if available
        if display_entity.last_action:
            action_text, action_rect = text_renderer.render_text(
                f"• {display_entity.last_action}", "small", self.colors["text"]["normal"]
            )
            action_rect.topleft = (x + 10, y)
            self.screen.blit(action_text, action_rect)
            y += line_height - 4
            
        # Display last market action if available
        if display_entity.last_market_action:
            # Truncate if too long for display
            market_action = display_entity.last_market_action
            if len(market_action) > 60:
                market_action = market_action[:57] + "..."
                
            market_action_text, market_action_rect = text_renderer.render_text(
                f"• {market_action}", "small", self.colors["text"]["normal"]
            )
            market_action_rect.topleft = (x + 10, y)
            self.screen.blit(market_action_text, market_action_rect)