from typing import Optional, Literal, Dict, List, Tuple, Any
import random
import math

try:
    import pygame
    from pygame import Rect, Color

    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False
    print("Warning: pygame not installed. Only headless mode available.")

from spacesim2.core.actor import ActorType, Actor
from spacesim2.core.commodity import CommodityType
from spacesim2.core.simulation import Simulation
from spacesim2.core.planet import Planet


# UI screen modes
ScreenMode = Literal["main", "actor_details"]


class PygameUI:
    """Graphical user interface using pygame."""

    def __init__(self, simulation: Simulation) -> None:
        self.simulation = simulation
        # New larger screen dimensions
        self.width = 1920
        self.height = 1080
        
        # Pane dimensions
        self.left_pane_width = 640
        self.center_pane_width = 640
        self.right_pane_width = 640
        
        # UI state
        self.active_pane = 1  # 0=left, 1=center, 2=right
        self.selected_planet: Optional[Planet] = None
        self.selected_actor: Optional[Actor] = None
        
        # Colors
        self.colors = {
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
            "ui_elements": {
                "button": (70, 70, 90),
                "button_hover": (90, 90, 120),
                "panel": (30, 30, 40),
            }
        }
        
        # Pygame objects
        self.screen: Optional[pygame.Surface] = None
        self.fonts: Dict[str, pygame.font.Font] = {}
        self.clock: Optional[pygame.time.Clock] = None
        self.running = False
        
        # Planet visualization
        self.planet_positions: Dict[Planet, Tuple[int, int]] = {}
        self.planet_radius = 40
        
        # Actor visualization
        self.actor_list_item_height = 40
        self.actor_list_scroll_offset = 0
        self.actor_list_visible_items = 20
        
        # Help text
        self.help_text = [
            "Space: Advance turn", 
            "Tab: Switch panes",
            "Arrow keys: Navigate",
            "Enter: Select item",
            "Esc: Quit",
        ]

    def initialize(self) -> bool:
        """Initialize pygame and set up the window."""
        if not PYGAME_AVAILABLE:
            return False

        pygame.init()
        pygame.display.set_caption("SpaceSim2")
        self.screen = pygame.display.set_mode((self.width, self.height))
        
        # Initialize fonts
        self.fonts = {
            "small": pygame.font.SysFont(None, 18),
            "normal": pygame.font.SysFont(None, 24),
            "large": pygame.font.SysFont(None, 32),
            "title": pygame.font.SysFont(None, 48),
        }
        
        self.clock = pygame.time.Clock()
        
        # Select first planet by default
        if self.simulation.planets:
            self.selected_planet = self.simulation.planets[0]
            
        # Generate planet positions in a grid or circle based on count
        self._generate_planet_positions()
        
        return True

    def _generate_planet_positions(self) -> None:
        """Generate positions for planets in the center pane."""
        if not self.simulation.planets:
            return
            
        planets = self.simulation.planets
        count = len(planets)
        
        # Center of the center pane
        center_x = self.left_pane_width + (self.center_pane_width // 2)
        center_y = self.height // 2
        
        # Clear existing positions
        self.planet_positions = {}
        
        if count <= 9:
            # Arrange in a grid for small numbers
            cols = min(3, count)
            rows = math.ceil(count / cols)
            
            spacing_x = min(150, self.center_pane_width // (cols + 1))
            spacing_y = min(150, self.height // (rows + 2))
            
            start_x = center_x - ((cols - 1) * spacing_x // 2)
            start_y = center_y - ((rows - 1) * spacing_y // 2)
            
            for i, planet in enumerate(planets):
                row = i // cols
                col = i % cols
                x = start_x + (col * spacing_x)
                y = start_y + (row * spacing_y)
                self.planet_positions[planet] = (x, y)
        else:
            # Arrange in a circle for larger numbers
            radius = min(self.center_pane_width, self.height) // 3
            
            for i, planet in enumerate(planets):
                angle = (2 * math.pi * i) / count
                x = center_x + int(radius * math.cos(angle))
                y = center_y + int(radius * math.sin(angle))
                self.planet_positions[planet] = (x, y)

    def handle_events(self) -> bool:
        """Handle pygame events. Return False to quit."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
                
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
                elif event.key == pygame.K_SPACE:
                    self.simulation.run_turn()
                elif event.key == pygame.K_TAB:
                    # Cycle through panes
                    self.active_pane = (self.active_pane + 1) % 3
                elif event.key == pygame.K_LEFT:
                    # Move to left pane
                    self.active_pane = max(0, self.active_pane - 1)
                elif event.key == pygame.K_RIGHT:
                    # Move to right pane
                    self.active_pane = min(2, self.active_pane + 1)
                    
                # Handle navigation within active pane
                self._handle_navigation_keys(event.key)
                
            elif event.type == pygame.MOUSEBUTTONDOWN:
                # Determine which pane was clicked
                x, y = event.pos
                if x < self.left_pane_width:
                    self.active_pane = 0
                    # Handle actor selection in left pane
                    self._handle_actor_pane_click(x, y)
                elif x < self.left_pane_width + self.center_pane_width:
                    self.active_pane = 1
                    # Handle planet selection in center pane
                    self._handle_planet_pane_click(x, y)
                else:
                    self.active_pane = 2
                    # Handle detail pane interaction
                    self._handle_detail_pane_click(x, y)
                    
                # Handle scroll wheel
                if event.button == 4:  # Scroll up
                    if self.active_pane == 0:  # Left pane (actor list)
                        self.actor_list_scroll_offset = max(0, self.actor_list_scroll_offset - 3)
                elif event.button == 5:  # Scroll down
                    if self.active_pane == 0:  # Left pane (actor list)
                        max_offset = max(0, len(self.selected_planet.actors) - self.actor_list_visible_items) if self.selected_planet else 0
                        self.actor_list_scroll_offset = min(max_offset, self.actor_list_scroll_offset + 3)
                
        return True
        
    def _handle_navigation_keys(self, key: int) -> None:
        """Handle navigation keys within the active pane."""
        if self.active_pane == 0:  # Left pane (actor list)
            if self.selected_planet and self.selected_planet.actors:
                if key == pygame.K_UP:
                    # Select previous actor or scroll up
                    if self.selected_actor in self.selected_planet.actors:
                        current_index = self.selected_planet.actors.index(self.selected_actor)
                        if current_index > 0:
                            self.selected_actor = self.selected_planet.actors[current_index - 1]
                            # Adjust scroll if needed
                            if current_index - 1 < self.actor_list_scroll_offset:
                                self.actor_list_scroll_offset = current_index - 1
                    else:
                        # No actor selected, select the last one
                        self.selected_actor = self.selected_planet.actors[-1]
                
                elif key == pygame.K_DOWN:
                    # Select next actor or scroll down
                    if self.selected_actor in self.selected_planet.actors:
                        current_index = self.selected_planet.actors.index(self.selected_actor)
                        if current_index < len(self.selected_planet.actors) - 1:
                            self.selected_actor = self.selected_planet.actors[current_index + 1]
                            # Adjust scroll if needed
                            if current_index + 1 >= self.actor_list_scroll_offset + self.actor_list_visible_items:
                                self.actor_list_scroll_offset = current_index + 1 - self.actor_list_visible_items + 1
                    else:
                        # No actor selected, select the first one
                        self.selected_actor = self.selected_planet.actors[0]
        
        elif self.active_pane == 1:  # Center pane (planet grid)
            # Basic navigation through planets
            if self.simulation.planets:
                current_index = self.simulation.planets.index(self.selected_planet) if self.selected_planet in self.simulation.planets else 0
                
                if key == pygame.K_UP or key == pygame.K_LEFT:
                    # Move to previous planet
                    if current_index > 0:
                        self.selected_planet = self.simulation.planets[current_index - 1]
                        # Clear actor selection when changing planets
                        self.selected_actor = None
                        
                elif key == pygame.K_DOWN or key == pygame.K_RIGHT:
                    # Move to next planet
                    if current_index < len(self.simulation.planets) - 1:
                        self.selected_planet = self.simulation.planets[current_index + 1]
                        # Clear actor selection when changing planets
                        self.selected_actor = None
                        
                elif key == pygame.K_RETURN:
                    # Focus on left pane to select an actor
                    self.active_pane = 0
    
    def _handle_actor_pane_click(self, x: int, y: int) -> None:
        """Handle clicks in the actor pane."""
        if not self.selected_planet:
            return
            
        # Calculate list boundaries
        list_start_y = 80  # Start position of the actor list
        
        # Check if click is in the actor list area
        if y >= list_start_y:
            # Calculate which actor was clicked
            relative_y = y - list_start_y
            index = self.actor_list_scroll_offset + (relative_y // self.actor_list_item_height)
            
            # Select the actor if valid
            if 0 <= index < len(self.selected_planet.actors):
                self.selected_actor = self.selected_planet.actors[index]
    
    def _handle_planet_pane_click(self, x: int, y: int) -> None:
        """Handle clicks in the planet pane."""
        # Check if any planet was clicked
        for planet, (planet_x, planet_y) in self.planet_positions.items():
            # Calculate distance from click to planet center
            distance = math.sqrt((x - planet_x) ** 2 + (y - planet_y) ** 2)
            
            # If click is inside planet
            if distance <= self.planet_radius:
                self.selected_planet = planet
                self.selected_actor = None
                break
    
    def _handle_detail_pane_click(self, x: int, y: int) -> None:
        """Handle clicks in the detail pane."""
        # Currently no interactive elements in detail pane
        pass

    def render(self) -> None:
        """Render the current state of the simulation."""
        if not self.screen:
            return

        # Clear screen with background color
        self.screen.fill(self.colors["background"])
        
        # Draw pane backgrounds if active
        if self.active_pane in self.colors["active_pane"]:
            if self.active_pane == 0:  # Left pane
                pygame.draw.rect(
                    self.screen, 
                    self.colors["active_pane"][0], 
                    (0, 0, self.left_pane_width, self.height)
                )
            elif self.active_pane == 1:  # Center pane
                pygame.draw.rect(
                    self.screen, 
                    self.colors["active_pane"][1], 
                    (self.left_pane_width, 0, self.center_pane_width, self.height)
                )
            elif self.active_pane == 2:  # Right pane
                pygame.draw.rect(
                    self.screen, 
                    self.colors["active_pane"][2], 
                    (self.left_pane_width + self.center_pane_width, 0, self.right_pane_width, self.height)
                )
        
        # Draw pane dividers
        pygame.draw.line(
            self.screen, 
            self.colors["pane_divider"], 
            (self.left_pane_width, 0), 
            (self.left_pane_width, self.height), 
            2
        )
        pygame.draw.line(
            self.screen, 
            self.colors["pane_divider"], 
            (self.left_pane_width + self.center_pane_width, 0), 
            (self.left_pane_width + self.center_pane_width, self.height), 
            2
        )
        
        # Render each pane
        self._render_actor_pane()
        self._render_planet_pane()
        self._render_detail_pane()
        
        # Draw turn counter and help bar at the bottom
        self._render_status_bar()
        
        # Update display
        pygame.display.flip()
        
    def _render_actor_pane(self) -> None:
        """Render the left pane with the actor list."""
        # Title
        if self.selected_planet:
            title = f"Actors on {self.selected_planet.name}"
        else:
            title = "No Planet Selected"
            
        title_text = self.fonts["large"].render(
            title, True, self.colors["text"]["header"]
        )
        self.screen.blit(title_text, (20, 20))
        
        # Subtitle with count
        actor_count = len(self.selected_planet.actors) if self.selected_planet else 0
        subtitle = f"{actor_count} actors"
        subtitle_text = self.fonts["normal"].render(
            subtitle, True, self.colors["text"]["normal"]
        )
        self.screen.blit(subtitle_text, (20, 50))
        
        # Draw actor list header
        header_y = 80
        pygame.draw.line(
            self.screen, 
            self.colors["pane_divider"], 
            (10, header_y - 5), 
            (self.left_pane_width - 10, header_y - 5), 
            1
        )
        
        # Draw scrollable actor list
        if not self.selected_planet or not self.selected_planet.actors:
            no_actors_text = self.fonts["normal"].render(
                "No actors available", True, self.colors["text"]["error"]
            )
            self.screen.blit(no_actors_text, (20, header_y + 20))
            return
            
        # Calculate visible range
        start_index = min(self.actor_list_scroll_offset, len(self.selected_planet.actors) - 1)
        end_index = min(start_index + self.actor_list_visible_items, len(self.selected_planet.actors))
        
        # Draw each actor in the visible range
        for i in range(start_index, end_index):
            actor = self.selected_planet.actors[i]
            y_pos = header_y + ((i - start_index) * self.actor_list_item_height)
            
            # Highlight if selected
            if actor == self.selected_actor:
                pygame.draw.rect(
                    self.screen,
                    self.colors["ui_elements"]["button_hover"],
                    (5, y_pos, self.left_pane_width - 10, self.actor_list_item_height - 2)
                )
            
            # Actor name and type
            name_color = self.colors["text"]["market_maker"] if actor.actor_type == ActorType.MARKET_MAKER else self.colors["text"]["normal"]
            name_text = self.fonts["normal"].render(f"{actor.name}", True, name_color)
            self.screen.blit(name_text, (20, y_pos + 10))
            
            # Actor money and food status in smaller text to the right
            food_qty = actor.inventory.get_quantity(CommodityType.RAW_FOOD) if hasattr(actor, "inventory") else 0
            money_text = self.fonts["small"].render(
                f"${actor.money:,}", True, self.colors["text"]["money"]
            )
            money_width = money_text.get_width()
            self.screen.blit(money_text, (self.left_pane_width - 20 - money_width, y_pos + 5))
            
            food_text = self.fonts["small"].render(
                f"Food: {food_qty}", True, self.colors["text"]["food"]
            )
            food_width = food_text.get_width()
            self.screen.blit(food_text, (self.left_pane_width - 20 - food_width, y_pos + 22))
        
        # Draw scroll indicators if needed
        if start_index > 0:
            # Up arrow
            pygame.draw.polygon(
                self.screen,
                self.colors["text"]["normal"],
                [(self.left_pane_width - 30, header_y + 20), (self.left_pane_width - 20, header_y + 5), (self.left_pane_width - 10, header_y + 20)]
            )
            
        if end_index < len(self.selected_planet.actors):
            # Down arrow
            bottom_y = header_y + (self.actor_list_visible_items * self.actor_list_item_height) + 20
            pygame.draw.polygon(
                self.screen,
                self.colors["text"]["normal"],
                [(self.left_pane_width - 30, bottom_y - 20), (self.left_pane_width - 20, bottom_y - 5), (self.left_pane_width - 10, bottom_y - 20)]
            )
            
    def _render_planet_pane(self) -> None:
        """Render the center pane with planets."""
        # Title
        title_text = self.fonts["large"].render(
            "Star System", True, self.colors["text"]["header"]
        )
        self.screen.blit(title_text, (self.left_pane_width + 20, 20))
        
        # Subtitle with count
        planet_count = len(self.simulation.planets)
        subtitle = f"{planet_count} planets"
        subtitle_text = self.fonts["normal"].render(
            subtitle, True, self.colors["text"]["normal"]
        )
        self.screen.blit(subtitle_text, (self.left_pane_width + 20, 50))
        
        # Draw planets
        if not self.simulation.planets:
            no_planets_text = self.fonts["normal"].render(
                "No planets in simulation", True, self.colors["text"]["error"]
            )
            self.screen.blit(
                no_planets_text, 
                (self.left_pane_width + (self.center_pane_width // 2) - (no_planets_text.get_width() // 2), 
                self.height // 2)
            )
            return
        
        # Draw each planet
        for planet in self.simulation.planets:
            if planet in self.planet_positions:
                pos_x, pos_y = self.planet_positions[planet]
                
                # Determine planet color
                planet_color = self.colors["planet"]["selected"] if planet == self.selected_planet else self.colors["planet"]["default"]
                
                # Draw planet
                pygame.draw.circle(
                    self.screen, planet_color, (pos_x, pos_y), self.planet_radius
                )
                
                # Draw outline for the selected planet
                if planet == self.selected_planet:
                    pygame.draw.circle(
                        self.screen, self.colors["planet"]["outline"], 
                        (pos_x, pos_y), self.planet_radius + 2, 2
                    )
                
                # Draw planet name
                name_text = self.fonts["normal"].render(planet.name, True, self.colors["text"]["planet"])
                name_rect = name_text.get_rect(center=(pos_x, pos_y + self.planet_radius + 20))
                self.screen.blit(name_text, name_rect)
                
                # Draw actor count
                actor_count = len(planet.actors)
                count_text = self.fonts["small"].render(
                    f"{actor_count} actors", True, self.colors["text"]["normal"]
                )
                count_rect = count_text.get_rect(center=(pos_x, pos_y))
                self.screen.blit(count_text, count_rect)
                
    def _render_detail_pane(self) -> None:
        """Render the right pane with details."""
        # Title changes based on what's selected
        if self.selected_actor:
            title = f"Details: {self.selected_actor.name}"
        elif self.selected_planet:
            title = f"Details: {self.selected_planet.name}"
        else:
            title = "Simulation Details"
            
        title_text = self.fonts["large"].render(
            title, True, self.colors["text"]["header"]
        )
        self.screen.blit(title_text, (self.left_pane_width + self.center_pane_width + 20, 20))
        
        # Panel background
        panel_rect = Rect(
            self.left_pane_width + self.center_pane_width + 20,
            80,
            self.right_pane_width - 40,
            self.height - 150
        )
        pygame.draw.rect(
            self.screen,
            self.colors["ui_elements"]["panel"],
            panel_rect,
            border_radius=5
        )
        
        # Content based on selection
        if self.selected_actor:
            self._render_actor_details(panel_rect)
        elif self.selected_planet:
            self._render_planet_details(panel_rect)
        else:
            self._render_simulation_details(panel_rect)
            
    def _render_actor_details(self, panel_rect: Rect) -> None:
        """Render detailed actor information."""
        if not self.selected_actor:
            return
            
        actor = self.selected_actor
        x, y = panel_rect.x + 20, panel_rect.y + 20
        line_height = 30
        
        # Actor type
        type_text = self.fonts["normal"].render(
            f"Type: {actor.actor_type.value}", 
            True, 
            self.colors["text"]["normal"]
        )
        self.screen.blit(type_text, (x, y))
        y += line_height
        
        # Money
        money_text = self.fonts["normal"].render(
            f"Money: ${actor.money:,}", 
            True, 
            self.colors["text"]["money"]
        )
        self.screen.blit(money_text, (x, y))
        y += line_height
        
        # Food status
        food_qty = actor.inventory.get_quantity(CommodityType.RAW_FOOD) if hasattr(actor, "inventory") else 0
        food_status = "✓" if hasattr(actor, "food_consumed_this_turn") and actor.food_consumed_this_turn else "✗"
        food_text = self.fonts["normal"].render(
            f"Food: {food_qty} {food_status}", 
            True, 
            self.colors["text"]["food"]
        )
        self.screen.blit(food_text, (x, y))
        y += line_height
        
        # Inventory section
        y += line_height // 2
        inventory_title = self.fonts["normal"].render(
            "Inventory:", True, self.colors["text"]["header"]
        )
        self.screen.blit(inventory_title, (x, y))
        y += line_height
        
        # List inventory items
        if hasattr(actor, "inventory"):
            # Get combined inventory (available and reserved)
            for commodity_type in CommodityType:
                quantity = actor.inventory.get_quantity(commodity_type)
                if quantity > 0:
                    available = actor.inventory.get_available_quantity(commodity_type)
                    reserved = actor.inventory.get_reserved_quantity(commodity_type)
                    
                    # Show total and breakdown if items are reserved
                    if reserved > 0:
                        item_text = self.fonts["normal"].render(
                            f"• {commodity_type.value}: {quantity} ({available} avail, {reserved} reserved)", 
                            True, 
                            self.colors["text"]["normal"]
                        )
                    else:
                        item_text = self.fonts["normal"].render(
                            f"• {commodity_type.value}: {quantity}", 
                            True, 
                            self.colors["text"]["normal"]
                        )
                    self.screen.blit(item_text, (x + 10, y))
                    y += line_height
        
        # Last actions section
        y += line_height // 2
        actions_title = self.fonts["normal"].render(
            "Recent Actions:", True, self.colors["text"]["header"]
        )
        self.screen.blit(actions_title, (x, y))
        y += line_height
        
        # Display last action
        if hasattr(actor, "last_action") and actor.last_action:
            action_text = self.fonts["normal"].render(
                f"• {actor.last_action}", 
                True, 
                self.colors["text"]["normal"]
            )
            self.screen.blit(action_text, (x + 10, y))
            y += line_height
            
        # Display last market action
        if hasattr(actor, "last_market_action") and actor.last_market_action:
            market_action_text = self.fonts["normal"].render(
                f"• {actor.last_market_action}", 
                True, 
                self.colors["text"]["normal"]
            )
            self.screen.blit(market_action_text, (x + 10, y))
        
    def _render_planet_details(self, panel_rect: Rect) -> None:
        """Render detailed planet information."""
        if not self.selected_planet:
            return
            
        planet = self.selected_planet
        x, y = panel_rect.x + 20, panel_rect.y + 20
        line_height = 30
        
        # Actor count
        actor_count_text = self.fonts["normal"].render(
            f"Actors: {len(planet.actors)}", 
            True, 
            self.colors["text"]["normal"]
        )
        self.screen.blit(actor_count_text, (x, y))
        y += line_height
        
        # Position
        position_text = self.fonts["normal"].render(
            f"Position: ({planet.x:.1f}, {planet.y:.1f})", 
            True, 
            self.colors["text"]["normal"]
        )
        self.screen.blit(position_text, (x, y))
        y += line_height * 2
        
        # Market information
        if planet.market:
            market_title = self.fonts["normal"].render(
                "Market Information:", True, self.colors["text"]["header"]
            )
            self.screen.blit(market_title, (x, y))
            y += line_height
            
            # List commodity prices
            for commodity_type in CommodityType:
                avg_price = planet.market.get_avg_price(commodity_type)
                price_text = self.fonts["normal"].render(
                    f"• {commodity_type.value}: ${avg_price:.2f}", 
                    True, 
                    self.colors["text"]["normal"]
                )
                self.screen.blit(price_text, (x + 10, y))
                y += line_height
        else:
            no_market_text = self.fonts["normal"].render(
                "No market on this planet", 
                True, 
                self.colors["text"]["error"]
            )
            self.screen.blit(no_market_text, (x, y))
        
    def _render_simulation_details(self, panel_rect: Rect) -> None:
        """Render simulation-wide information."""
        x, y = panel_rect.x + 20, panel_rect.y + 20
        line_height = 30
        
        # Current turn
        turn_text = self.fonts["normal"].render(
            f"Current Turn: {self.simulation.current_turn}", 
            True, 
            self.colors["text"]["normal"]
        )
        self.screen.blit(turn_text, (x, y))
        y += line_height
        
        # Planet count
        planet_count_text = self.fonts["normal"].render(
            f"Planets: {len(self.simulation.planets)}", 
            True, 
            self.colors["text"]["normal"]
        )
        self.screen.blit(planet_count_text, (x, y))
        y += line_height
        
        # Total actors
        total_actors = sum(len(planet.actors) for planet in self.simulation.planets)
        actors_text = self.fonts["normal"].render(
            f"Total Actors: {total_actors}", 
            True, 
            self.colors["text"]["normal"]
        )
        self.screen.blit(actors_text, (x, y))
        y += line_height * 2
        
        # Economy overview
        economy_title = self.fonts["normal"].render(
            "Economy Overview:", True, self.colors["text"]["header"]
        )
        self.screen.blit(economy_title, (x, y))
        y += line_height
        
        # Calculate total money and food in the system
        total_money = 0
        total_food = 0
        for planet in self.simulation.planets:
            for actor in planet.actors:
                total_money += actor.money
                if hasattr(actor, "inventory"):
                    total_food += actor.inventory.get_quantity(CommodityType.RAW_FOOD)
        
        money_text = self.fonts["normal"].render(
            f"• Total Money: ${total_money:,}", 
            True, 
            self.colors["text"]["money"]
        )
        self.screen.blit(money_text, (x + 10, y))
        y += line_height
        
        food_text = self.fonts["normal"].render(
            f"• Total Food: {total_food}", 
            True, 
            self.colors["text"]["food"]
        )
        self.screen.blit(food_text, (x + 10, y))
        
    def _render_status_bar(self) -> None:
        """Render the status bar at the bottom of the screen."""
        # Draw background
        status_bar_height = 40
        pygame.draw.rect(
            self.screen,
            self.colors["ui_elements"]["panel"],
            (0, self.height - status_bar_height, self.width, status_bar_height)
        )
        
        # Draw turn counter
        turn_text = self.fonts["normal"].render(
            f"Turn: {self.simulation.current_turn}", 
            True, 
            self.colors["text"]["highlight"]
        )
        self.screen.blit(turn_text, (20, self.height - status_bar_height + 10))
        
        # Draw help text
        help_x = 200
        for help_item in self.help_text:
            help_item_text = self.fonts["small"].render(
                help_item, True, self.colors["text"]["normal"]
            )
            self.screen.blit(help_item_text, (help_x, self.height - status_bar_height + 13))
            help_x += help_item_text.get_width() + 30

    def run(self, auto_turns: int = 0) -> None:
        """Run the pygame UI loop.

        Args:
            auto_turns: If greater than 0, automatically run this many turns
                        and then wait for user input.
        """
        if not self.initialize():
            print("Failed to initialize pygame UI. Exiting.")
            return

        self.running = True
        turn_counter = 0

        while self.running:
            # Handle automatic turns
            if auto_turns > 0 and turn_counter < auto_turns:
                self.simulation.run_turn()
                turn_counter += 1

            # Handle events
            self.running = self.handle_events()

            # Render
            self.render()

            # Cap at 60 FPS
            if self.clock:
                self.clock.tick(60)

        # Clean up
        pygame.quit()