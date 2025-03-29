from typing import Optional

try:
    import pygame

    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False
    print("Warning: pygame not installed. Only headless mode available.")

from spacesim2.core.actor import ActorType
from spacesim2.core.commodity import CommodityType
from spacesim2.core.simulation import Simulation


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
        return True

    def render(self) -> None:
        """Render the current state of the simulation."""
        if not self.screen or not self.font:
            return

        # Clear screen
        self.screen.fill((0, 0, 0))

        # Draw turn counter
        turn_text = self.font.render(
            f"Turn: {self.simulation.current_turn}", True, (255, 255, 255)
        )
        self.screen.blit(turn_text, (10, 10))
        
        # Draw market information if available
        if self.simulation.planets and self.simulation.planets[0].market:
            market = self.simulation.planets[0].market
            food_price = market.get_avg_price(market.CommodityType.RAW_FOOD)
            
            market_text = self.font.render(
                f"Market: Raw Food Price: {food_price:.2f}", True, (150, 220, 150)
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
                        f"  [MM] {actor.name}: {actor.money:.1f} credits, {food_qty} food {food_status}", 
                        True, (220, 180, 50)  # Gold for market makers
                    )
                else:
                    actor_text = self.font.render(
                        f"  {actor.name}: {actor.money:.1f} credits, {food_qty} food {food_status}", 
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

        # Update display
        pygame.display.flip()

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
