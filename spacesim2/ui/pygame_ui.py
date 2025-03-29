from typing import Optional, Literal

try:
    import pygame

    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False
    print("Warning: pygame not installed. Only headless mode available.")

from spacesim2.core.actor import ActorType
from spacesim2.core.commodity import CommodityType
from spacesim2.core.simulation import Simulation


# UI screen modes
ScreenMode = Literal["main", "actor_details"]


class PygameUI:
    """Graphical user interface using pygame."""

    def __init__(self, simulation: Simulation) -> None:
        self.simulation = simulation
        self.width = 800
        self.height = 600
        self.screen: Optional[pygame.Surface] = None
        self.font: Optional[pygame.font.Font] = None
        self.clock: Optional[pygame.time.Clock] = None
        self.running = False
        self.current_screen: ScreenMode = "main"

    def initialize(self) -> bool:
        """Initialize pygame and set up the window."""
        if not PYGAME_AVAILABLE:
            return False

        pygame.init()
        pygame.display.set_caption("SpaceSim2")
        self.screen = pygame.display.set_mode((self.width, self.height))
        self.font = pygame.font.SysFont(None, 24)
        self.clock = pygame.time.Clock()
        return True

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
                    # Toggle between screens
                    self.current_screen = "actor_details" if self.current_screen == "main" else "main"
        return True

    def render(self) -> None:
        """Render the current state of the simulation."""
        if not self.screen or not self.font:
            return

        # Clear screen
        self.screen.fill((0, 0, 0))

        # Draw turn counter (shown on all screens)
        turn_text = self.font.render(
            f"Turn: {self.simulation.current_turn}", True, (255, 255, 255)
        )
        self.screen.blit(turn_text, (10, 10))
        
        # Render appropriate screen
        if self.current_screen == "main":
            self._render_main_screen()
        elif self.current_screen == "actor_details":
            self._render_actor_details_screen()

        # Show navigation help at bottom of screen
        navigation_text = self.font.render(
            "Press TAB to switch screens, SPACE to advance turn, ESC to quit", 
            True, (150, 150, 150)
        )
        self.screen.blit(navigation_text, (10, self.height - 30))
            
        # Update display
        pygame.display.flip()
        
    def _render_main_screen(self) -> None:
        """Render the main overview screen."""
        if not self.screen or not self.font:
            return
            
        # Draw market information if available
        if self.simulation.planets and self.simulation.planets[0].market:
            market = self.simulation.planets[0].market
            food_price = market.get_avg_price(CommodityType.RAW_FOOD)
            
            market_text = self.font.render(
                f"Market: Raw Food Price: {food_price}", True, (150, 220, 150)
            )
            self.screen.blit(market_text, (250, 10))

        # Draw actor information
        y_pos = 50
        actor_count = 0

        for planet in self.simulation.planets:
            planet_label = self.font.render(
                f"Planet: {planet.name}", True, (200, 200, 200)
            )
            self.screen.blit(planet_label, (10, y_pos + actor_count * 25))
            actor_count += 1

            for actor in planet.actors:
                food_qty = actor.inventory.get_quantity(CommodityType.RAW_FOOD) if hasattr(actor, "inventory") else 0
                
                food_status = "✓" if hasattr(actor, "food_consumed_this_turn") and actor.food_consumed_this_turn else "✗"
                
                # Format based on actor type
                if hasattr(actor, "actor_type") and actor.actor_type == ActorType.MARKET_MAKER:
                    actor_text = self.font.render(
                        f"  [MM] {actor.name}: {actor.money} credits, {food_qty} food {food_status}", 
                        True, (220, 180, 50)  # Gold for market makers
                    )
                else:
                    actor_text = self.font.render(
                        f"  {actor.name}: {actor.money} credits, {food_qty} food {food_status}", 
                        True, (255, 255, 255)
                    )
                    
                self.screen.blit(actor_text, (10, y_pos + actor_count * 25))
                actor_count += 1

        # Draw planet
        if self.simulation.planets:
            planet = self.simulation.planets[0]
            pygame.draw.circle(
                self.screen, (0, 0, 255), (self.width // 2, self.height // 2), 50
            )
            planet_text = self.font.render(planet.name, True, (255, 255, 255))
            text_rect = planet_text.get_rect(
                center=(self.width // 2, self.height // 2 + 70)
            )
            self.screen.blit(planet_text, text_rect)
            
    def _render_actor_details_screen(self) -> None:
        """Render the detailed actor information screen."""
        if not self.screen or not self.font:
            return
            
        # Screen title
        title_text = self.font.render("Actor Details", True, (255, 255, 255))
        self.screen.blit(title_text, (self.width // 2 - 50, 40))
        
        # Column headers
        headers = [
            ("Name", 10),
            ("Type", 140),
            ("Money", 220),
            ("Food", 310),
            ("Last Action", 370),
            ("Last Market Action", 10)
        ]
        
        # Draw headers
        y_pos = 80
        for header, x_pos in headers:
            header_text = self.font.render(header, True, (200, 200, 200))
            if header == "Last Market Action":
                # Position this on the next line
                self.screen.blit(header_text, (x_pos, y_pos + 20))
            else:
                self.screen.blit(header_text, (x_pos, y_pos))
        
        # Draw horizontal separator
        pygame.draw.line(
            self.screen, 
            (100, 100, 100), 
            (10, y_pos + 40), 
            (self.width - 10, y_pos + 40), 
            1
        )
        
        # Draw actor details
        row_height = 60
        actor_index = 0
        
        for planet in self.simulation.planets:
            # Planet header
            planet_y = y_pos + 50 + (actor_index * row_height)
            planet_text = self.font.render(
                f"Planet: {planet.name}", True, (150, 150, 240)
            )
            self.screen.blit(planet_text, (10, planet_y))
            actor_index += 1
            
            # Actor information
            for actor in planet.actors:
                actor_y = y_pos + 50 + (actor_index * row_height)
                
                # Actor name with type indicator
                type_indicator = "[MM]" if actor.actor_type == ActorType.MARKET_MAKER else ""
                name_color = (220, 180, 50) if actor.actor_type == ActorType.MARKET_MAKER else (255, 255, 255)
                name_text = self.font.render(f"{actor.name}", True, name_color)
                self.screen.blit(name_text, (10, actor_y))
                
                # Actor type
                type_text = self.font.render(f"{type_indicator} {actor.actor_type.value}", True, name_color)
                self.screen.blit(type_text, (140, actor_y))
                
                # Money
                money_text = self.font.render(f"{actor.money} credits", True, (150, 255, 150))
                self.screen.blit(money_text, (220, actor_y))
                
                # Food with consumption indicator
                food_qty = actor.inventory.get_quantity(CommodityType.RAW_FOOD)
                food_status = "✓" if actor.food_consumed_this_turn else "✗"
                food_text = self.font.render(f"{food_qty} {food_status}", True, (255, 200, 100))
                self.screen.blit(food_text, (310, actor_y))
                
                # Last action
                action_text = self.font.render(f"{actor.last_action}", True, (200, 200, 200))
                self.screen.blit(action_text, (370, actor_y))
                
                # Last market action (on second line)
                market_action_text = self.font.render(f"{actor.last_market_action}", True, (180, 180, 180))
                self.screen.blit(market_action_text, (10, actor_y + 20))
                
                # Divider line between actors
                pygame.draw.line(
                    self.screen, 
                    (50, 50, 50), 
                    (10, actor_y + row_height - 10), 
                    (self.width - 10, actor_y + row_height - 10), 
                    1
                )
                
                actor_index += 1

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
