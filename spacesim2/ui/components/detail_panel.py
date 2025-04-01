from typing import Dict, List, Optional, Tuple
import pygame
from pygame import Rect, Surface

from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.ship import Ship, ShipStatus
from spacesim2.core.planet import Planet
from spacesim2.core.commodity import CommodityDefinition
from spacesim2.core.simulation import Simulation
from spacesim2.ui.utils.text import TextRenderer
from spacesim2.ui.renderers.ui_renderer import UIRenderer

class DetailPanel:
    """Component for displaying detailed information about selected entities."""
    
    def __init__(self, screen: Surface, colors: Dict, 
                 x: int, y: int, width: int, height: int) -> None:
        """Initialize the detail panel.
        
        Args:
            screen: Pygame surface to render on
            colors: Dictionary of UI colors
            x: Panel x position
            y: Panel y position
            width: Panel width
            height: Panel height
        """
        self.screen = screen
        self.colors = colors
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        
        # UI renderers
        self.ui_renderer = UIRenderer(screen, colors)
        
        # Current state
        self.selected_planet: Optional[Planet] = None
        self.selected_actor: Optional[Actor] = None
        self.selected_ship: Optional[Ship] = None
        self.selected_commodity: Optional[CommodityDefinition] = None
        self.simulation: Optional[Simulation] = None
        
    def set_simulation(self, simulation: Simulation) -> None:
        """Set the simulation reference."""
        self.simulation = simulation
        
    def set_selected_planet(self, planet: Optional[Planet]) -> None:
        """Set the currently selected planet."""
        self.selected_planet = planet
        
    def set_selected_actor(self, actor: Optional[Actor]) -> None:
        """Set the currently selected actor."""
        self.selected_actor = actor
        
    def set_selected_ship(self, ship: Optional[Ship]) -> None:
        """Set the currently selected ship."""
        self.selected_ship = ship
        
    def set_selected_commodity(self, commodity: Optional[CommodityDefinition]) -> None:
        """Set the currently selected commodity."""
        self.selected_commodity = commodity
        
    def handle_click(self, x: int, y: int) -> bool:
        """Handle mouse click within the detail panel.
        
        Args:
            x: Mouse x position
            y: Mouse y position
            
        Returns:
            Whether the click was handled by this component
        """
        # Check if we're in planet details with a market
        if self.selected_planet and self.selected_planet.market:
            # Calculate the commodity list area
            panel_rect = Rect(
                self.x + 20,
                80,
                self.width - 40,
                self.height - 150
            )
            x_relative = x - panel_rect.x
            y_relative = y - panel_rect.y
            
            # Check if click is in the commodity list area
            if 0 <= x_relative <= panel_rect.width:
                # Start position of commodity list (header + instruction)
                commodity_start_y = 60  
                line_height = 30
                
                # Calculate which commodity was clicked (rough estimate)
                if y_relative >= commodity_start_y:
                    commodity_index = (y_relative - commodity_start_y) // line_height
                    
                    # Select the commodity if valid
                    commodity_registry = self.simulation.commodity_registry if self.simulation else None
                    if commodity_registry:
                        commodity_list = commodity_registry.all_commodities()
                        if 0 <= commodity_index < len(commodity_list):
                            # If already selected, deselect it
                            if self.selected_commodity == commodity_list[commodity_index]:
                                self.selected_commodity = None
                            else:
                                self.selected_commodity = commodity_list[commodity_index]
                            return True
                            
        return False
        
    def handle_key(self, key: int) -> bool:
        """Handle key press for detail panel interaction.
        
        Args:
            key: Pygame key constant
            
        Returns:
            Whether the key was handled by this component
        """
        # When in planet details, allow commodity selection
        if self.selected_planet and self.selected_planet.market:
            # Get list of available commodities
            commodity_registry = self.simulation.commodity_registry if self.simulation else None
            if not commodity_registry:
                return False
                
            commodity_list = commodity_registry.all_commodities()
            
            if not commodity_list:
                return False
                
            current_index = -1
            for i, commodity in enumerate(commodity_list):
                if self.selected_commodity == commodity:
                    current_index = i
                    break
            
            if key == pygame.K_UP:
                # Select previous commodity
                if current_index > 0:
                    self.selected_commodity = commodity_list[current_index - 1]
                elif current_index == -1:
                    # No commodity selected, select the last one
                    self.selected_commodity = commodity_list[-1]
                return True
                
            elif key == pygame.K_DOWN:
                # Select next commodity
                if current_index < len(commodity_list) - 1:
                    self.selected_commodity = commodity_list[current_index + 1]
                elif current_index == -1:
                    # No commodity selected, select the first one
                    self.selected_commodity = commodity_list[0]
                return True
                
            elif key == pygame.K_RETURN:
                # Toggle commodity selection
                if self.selected_commodity:
                    self.selected_commodity = None
                elif commodity_list:
                    self.selected_commodity = commodity_list[0]
                return True
                
        return False
    
    def render(self, text_renderer: TextRenderer) -> None:
        """Render the detail panel.
        
        Args:
            text_renderer: TextRenderer for rendering text
        """
        # Title changes based on what's selected
        if self.selected_ship:
            title = f"Ship Details: {self.selected_ship.name}"
        elif self.selected_actor:
            title = f"Actor Details: {self.selected_actor.name}"
        elif self.selected_planet:
            title = f"Planet Details: {self.selected_planet.name}"
        else:
            title = "Simulation Details"
            
        title_surface, title_rect = text_renderer.render_text(
            title, "large", self.colors["text"]["header"]
        )
        title_rect.topleft = (self.x + 20, 20)
        self.screen.blit(title_surface, title_rect)
        
        # Panel background
        panel_rect = Rect(
            self.x + 20,
            80,
            self.width - 40,
            self.height - 150
        )
        self.ui_renderer.draw_panel(panel_rect, border_radius=5)
        
        # Content based on selection
        if self.selected_ship:
            self._render_ship_details(panel_rect, text_renderer)
        elif self.selected_actor:
            self._render_actor_details(panel_rect, text_renderer)
        elif self.selected_planet:
            self._render_planet_details(panel_rect, text_renderer)
        else:
            self._render_simulation_details(panel_rect, text_renderer)
            
    def _render_ship_details(self, panel_rect: Rect, text_renderer: TextRenderer) -> None:
        """Render detailed ship information."""
        if not self.selected_ship:
            return
            
        ship = self.selected_ship
        x, y = panel_rect.x + 20, panel_rect.y + 20
        line_height = 30
        
        # Ship status
        status_color = self.colors["text"]["normal"]
        if ship.status == ShipStatus.TRAVELING:
            status_color = self.colors["ship"]["in_transit"]
        elif ship.status == ShipStatus.NEEDS_MAINTENANCE:
            status_color = self.colors["ship"]["needs_maintenance"]
            
        status_text, status_rect = text_renderer.render_text(
            f"Status: {ship.status.value}", "normal", status_color
        )
        status_rect.topleft = (x, y)
        self.screen.blit(status_text, status_rect)
        y += line_height
        
        # Current location
        if ship.status == ShipStatus.TRAVELING:
            location_text, location_rect = text_renderer.render_text(
                f"Traveling: {ship.planet.name} → {ship.destination.name} ({int(ship.travel_progress * 100)}%)", 
                "normal", 
                self.colors["text"]["normal"]
            )
        else:
            location_text, location_rect = text_renderer.render_text(
                f"Location: {ship.planet.name if ship.planet else 'Unknown'}", 
                "normal", 
                self.colors["text"]["normal"]
            )
        location_rect.topleft = (x, y)
        self.screen.blit(location_text, location_rect)
        y += line_height
        
        # Money
        money_text, money_rect = text_renderer.render_text(
            f"Money: ${ship.money:,}", "normal", self.colors["text"]["money"]
        )
        money_rect.topleft = (x, y)
        self.screen.blit(money_text, money_rect)
        y += line_height
        
        # Cargo and capacity
        cargo_used = ship.cargo.get_total_quantity()
        capacity_text, capacity_rect = text_renderer.render_text(
            f"Cargo: {cargo_used}/{ship.cargo_capacity} units used", 
            "normal", 
            self.colors["text"]["normal"]
        )
        capacity_rect.topleft = (x, y)
        self.screen.blit(capacity_text, capacity_rect)
        y += line_height
        
        # Fuel capacity and efficiency
        fuel = None
        if hasattr(ship, "cargo") and hasattr(ship.cargo, "commodities"):
            for commodity in ship.cargo.commodities:
                if commodity.id == "fuel":
                    fuel = commodity
                    break
        
        fuel_amount = ship.cargo.get_quantity(fuel) if fuel else 0
        fuel_text, fuel_rect = text_renderer.render_text(
            f"Fuel: {fuel_amount}/{ship.fuel_capacity} units (Efficiency: {ship.fuel_efficiency:.2f})", 
            "normal", 
            self.colors["text"]["normal"]
        )
        fuel_rect.topleft = (x, y)
        self.screen.blit(fuel_text, fuel_rect)
        y += line_height * 1.5
        
        # Cargo section
        cargo_title, cargo_title_rect = text_renderer.render_text(
            "Cargo Manifest:", "normal", self.colors["text"]["header"]
        )
        cargo_title_rect.topleft = (x, y)
        self.screen.blit(cargo_title, cargo_title_rect)
        y += line_height
        
        # List cargo items
        has_cargo = False
        if hasattr(ship, "cargo") and hasattr(ship.cargo, "commodities"):
            for commodity_id, quantity in ship.cargo.commodities.items():
                if quantity > 0:
                    has_cargo = True
                    item_text, item_rect = text_renderer.render_text(
                        f"• {commodity_id.name}: {quantity}", "normal", self.colors["text"]["normal"]
                    )
                    item_rect.topleft = (x + 10, y)
                    self.screen.blit(item_text, item_rect)
                    y += line_height
                
        if not has_cargo:
            empty_text, empty_rect = text_renderer.render_text(
                "• Empty cargo hold", "normal", self.colors["text"]["normal"]
            )
            empty_rect.topleft = (x + 10, y)
            self.screen.blit(empty_text, empty_rect)
            y += line_height
            
        # Last action section
        y += line_height // 2
        action_title, action_title_rect = text_renderer.render_text(
            "Last Action:", "normal", self.colors["text"]["header"]
        )
        action_title_rect.topleft = (x, y)
        self.screen.blit(action_title, action_title_rect)
        y += line_height
        
        # Display last action
        if hasattr(ship, "last_action") and ship.last_action:
            action_text, action_rect = text_renderer.render_text(
                f"• {ship.last_action}", "normal", self.colors["text"]["normal"]
            )
            action_rect.topleft = (x + 10, y)
            self.screen.blit(action_text, action_rect)
            
    def _render_actor_details(self, panel_rect: Rect, text_renderer: TextRenderer) -> None:
        """Render detailed actor information."""
        if not self.selected_actor:
            return
            
        actor = self.selected_actor
        x, y = panel_rect.x + 20, panel_rect.y + 20
        line_height = 30
        
        # Actor type
        type_text, type_rect = text_renderer.render_text(
            f"Type: {actor.actor_type.value}", "normal", self.colors["text"]["normal"]
        )
        type_rect.topleft = (x, y)
        self.screen.blit(type_text, type_rect)
        y += line_height
        
        # Money
        money_text, money_rect = text_renderer.render_text(
            f"Money: ${actor.money:,}", "normal", self.colors["text"]["money"]
        )
        money_rect.topleft = (x, y)
        self.screen.blit(money_text, money_rect)
        y += line_height
        
        # Food status
        raw_food = None
        if hasattr(actor, "inventory") and hasattr(actor.inventory, "commodities"):
            for commodity in actor.inventory.commodities:
                if commodity.id == "raw_food":
                    raw_food = commodity
                    break
        
        food_qty = actor.inventory.get_quantity(raw_food) if raw_food and hasattr(actor, "inventory") else 0
        food_status = "✓" if hasattr(actor, "food_consumed_this_turn") and actor.food_consumed_this_turn else "✗"
        food_text, food_rect = text_renderer.render_text(
            f"Food: {food_qty} {food_status}", "normal", self.colors["text"]["food"]
        )
        food_rect.topleft = (x, y)
        self.screen.blit(food_text, food_rect)
        y += line_height
        
        # Inventory section
        y += line_height // 2
        inventory_title, inventory_title_rect = text_renderer.render_text(
            "Inventory:", "normal", self.colors["text"]["header"]
        )
        inventory_title_rect.topleft = (x, y)
        self.screen.blit(inventory_title, inventory_title_rect)
        y += line_height
        
        # List inventory items
        if hasattr(actor, "inventory") and hasattr(actor.inventory, "commodities"):
            # Get combined inventory (available and reserved)
            commodity_registry = self.simulation.commodity_registry if self.simulation else None
            if commodity_registry:
                for commodity in commodity_registry.all_commodities():
                    quantity = actor.inventory.get_quantity(commodity)
                    if quantity > 0:
                        available = actor.inventory.get_available_quantity(commodity)
                        reserved = actor.inventory.get_reserved_quantity(commodity)
                        
                        # Show total and breakdown if items are reserved
                        if reserved > 0:
                            item_text, item_rect = text_renderer.render_text(
                                f"• {commodity.name}: {quantity} ({available} avail, {reserved} reserved)", 
                                "normal", 
                                self.colors["text"]["normal"]
                            )
                        else:
                            item_text, item_rect = text_renderer.render_text(
                                f"• {commodity.name}: {quantity}", "normal", self.colors["text"]["normal"]
                            )
                        item_rect.topleft = (x + 10, y)
                        self.screen.blit(item_text, item_rect)
                        y += line_height
        
        # Last actions section
        y += line_height // 2
        actions_title, actions_title_rect = text_renderer.render_text(
            "Recent Actions:", "normal", self.colors["text"]["header"]
        )
        actions_title_rect.topleft = (x, y)
        self.screen.blit(actions_title, actions_title_rect)
        y += line_height
        
        # Display last action
        if hasattr(actor, "last_action") and actor.last_action:
            action_text, action_rect = text_renderer.render_text(
                f"• {actor.last_action}", "normal", self.colors["text"]["normal"]
            )
            action_rect.topleft = (x + 10, y)
            self.screen.blit(action_text, action_rect)
            y += line_height
            
        # Display last market action
        if hasattr(actor, "last_market_action") and actor.last_market_action:
            market_action_text, market_action_rect = text_renderer.render_text(
                f"• {actor.last_market_action}", "normal", self.colors["text"]["normal"]
            )
            market_action_rect.topleft = (x + 10, y)
            self.screen.blit(market_action_text, market_action_rect)
            
    def _render_planet_details(self, panel_rect: Rect, text_renderer: TextRenderer) -> None:
        """Render detailed planet information."""
        if not self.selected_planet:
            return
            
        planet = self.selected_planet
        x, y = panel_rect.x + 20, panel_rect.y + 20
        line_height = 30
        
        # Actor count
        actor_count_text, actor_count_rect = text_renderer.render_text(
            f"Actors: {len(planet.actors)}", "normal", self.colors["text"]["normal"]
        )
        actor_count_rect.topleft = (x, y)
        self.screen.blit(actor_count_text, actor_count_rect)
        y += line_height
        
        # Position
        position_text, position_rect = text_renderer.render_text(
            f"Position: ({planet.x:.1f}, {planet.y:.1f})", "normal", self.colors["text"]["normal"]
        )
        position_rect.topleft = (x, y)
        self.screen.blit(position_text, position_rect)
        y += line_height * 2
        
        # Market information
        if planet.market:
            market_title, market_title_rect = text_renderer.render_text(
                "Market Information:", "normal", self.colors["text"]["header"]
            )
            market_title_rect.topleft = (x, y)
            self.screen.blit(market_title, market_title_rect)
            y += line_height
            
            instruction_text, instruction_rect = text_renderer.render_text(
                "Select a commodity to view orders (Enter to select)", "small", self.colors["text"]["normal"]
            )
            instruction_rect.topleft = (x + 10, y)
            self.screen.blit(instruction_text, instruction_rect)
            y += line_height
            
            # List commodity prices
            commodity_registry = self.simulation.commodity_registry if self.simulation else None
            if commodity_registry:
                for commodity in commodity_registry.all_commodities():
                    avg_price = planet.market.get_avg_price(commodity)
                    highest_bid, lowest_ask = planet.market.get_bid_ask_spread(commodity)
                    bid_ask_str = ""
                    if highest_bid is not None and lowest_ask is not None:
                        bid_ask_str = f" (Bid: ${highest_bid}, Ask: ${lowest_ask})"
                    
                    # Highlight selected commodity
                    if commodity == self.selected_commodity:
                        # Draw selection background
                        pygame.draw.rect(
                            self.screen,
                            self.colors["ui_elements"]["button_hover"],
                            (x, y, panel_rect.width - 40, line_height),
                            border_radius=3
                        )
                        text_color = self.colors["text"]["highlight"]
                    else:
                        text_color = self.colors["text"]["normal"]
                    
                    price_text, price_rect = text_renderer.render_text(
                        f"• {commodity.name}: ${avg_price:.2f}{bid_ask_str}", "normal", text_color
                    )
                    price_rect.topleft = (x + 10, y)
                    self.screen.blit(price_text, price_rect)
                    y += line_height
            
            # If a commodity is selected, show orders
            if self.selected_commodity and planet.market:
                y += line_height
                self._render_commodity_orders(panel_rect, x, y, text_renderer)
        else:
            no_market_text, no_market_rect = text_renderer.render_text(
                "No market on this planet", "normal", self.colors["text"]["error"]
            )
            no_market_rect.topleft = (x, y)
            self.screen.blit(no_market_text, no_market_rect)
            
    def _render_commodity_orders(self, panel_rect: Rect, x: int, y: int, text_renderer: TextRenderer) -> None:
        """Render order book and transaction history for selected commodity."""
        if not self.selected_planet or not self.selected_planet.market or not self.selected_commodity:
            return
            
        market = self.selected_planet.market
        commodity = self.selected_commodity
        line_height = 25  # Smaller line height for orders
        
        # Draw section headers
        orders_title, orders_title_rect = text_renderer.render_text(
            f"Order Book - {commodity.value}", "normal", self.colors["text"]["header"]
        )
        orders_title_rect.topleft = (x, y)
        self.screen.blit(orders_title, orders_title_rect)
        y += line_height * 1.2
        
        # Get buy and sell orders
        buy_orders = sorted(
            market.buy_orders.get(commodity, []),
            key=lambda o: (-o.price, o.timestamp)  # Highest price first
        )
        sell_orders = sorted(
            market.sell_orders.get(commodity, []),
            key=lambda o: (o.price, o.timestamp)   # Lowest price first
        )
        
        # Get only current turn's transactions for this commodity
        current_transactions = []
        if hasattr(market, "transaction_history") and self.simulation:
            current_transactions = [tx for tx in market.transaction_history 
                                  if tx.commodity_type == commodity and tx.turn == self.simulation.current_turn]
        
        # Draw column headers
        col_width = (panel_rect.width - 40) // 2
        buy_header_x = x
        sell_header_x = x + col_width
        
        # Buy orders header
        buy_header, buy_header_rect = text_renderer.render_text(
            "BUY ORDERS (Price | Quantity | Actor)", "small", (150, 255, 150)  # Green for buy
        )
        buy_header_rect.topleft = (buy_header_x, y)
        self.screen.blit(buy_header, buy_header_rect)
        
        # Sell orders header
        sell_header, sell_header_rect = text_renderer.render_text(
            "SELL ORDERS (Price | Quantity | Actor)", "small", (255, 150, 150)  # Red for sell
        )
        sell_header_rect.topleft = (sell_header_x, y)
        self.screen.blit(sell_header, sell_header_rect)
        
        y += line_height
        
        # Draw divider line
        pygame.draw.line(
            self.screen, 
            self.colors["pane_divider"], 
            (x, y - 5), 
            (panel_rect.x + panel_rect.width - 20, y - 5), 
            1
        )
        
        # Determine how many orders to show
        max_orders = 8
        visible_buy_orders = buy_orders[:max_orders]
        visible_sell_orders = sell_orders[:max_orders]
        
        # Draw buy orders
        order_y = y
        for i, order in enumerate(visible_buy_orders):
            order_text, order_rect = text_renderer.render_text(
                f"${order.price} | {order.quantity} | {order.actor.name[:10]}", 
                "small", 
                (150, 255, 150)  # Green for buy
            )
            order_rect.topleft = (buy_header_x + 10, order_y)
            self.screen.blit(order_text, order_rect)
            order_y += line_height
        
        # Draw sell orders
        order_y = y
        for i, order in enumerate(visible_sell_orders):
            order_text, order_rect = text_renderer.render_text(
                f"${order.price} | {order.quantity} | {order.actor.name[:10]}", 
                "small", 
                (255, 150, 150)  # Red for sell
            )
            order_rect.topleft = (sell_header_x + 10, order_y)
            self.screen.blit(order_text, order_rect)
            order_y += line_height
        
        # Update y position for transaction history
        y += max(len(visible_buy_orders), len(visible_sell_orders)) * line_height + line_height
        
        # Transaction history for current turn only
        if current_transactions:
            history_title, history_title_rect = text_renderer.render_text(
                "This Turn's Transactions", "normal", self.colors["text"]["header"]
            )
            history_title_rect.topleft = (x, y)
            self.screen.blit(history_title, history_title_rect)
            y += line_height
            
            # Draw column headers
            history_header, history_header_rect = text_renderer.render_text(
                "Price | Quantity | Buyer | Seller", "small", self.colors["text"]["normal"]
            )
            history_header_rect.topleft = (x + 10, y)
            self.screen.blit(history_header, history_header_rect)
            y += line_height
            
            # Draw divider line
            pygame.draw.line(
                self.screen, 
                self.colors["pane_divider"], 
                (x, y - 5), 
                (panel_rect.x + panel_rect.width - 20, y - 5), 
                1
            )
            
            # Draw transactions in reverse chronological order (newest first)
            for tx in reversed(current_transactions):
                tx_text, tx_rect = text_renderer.render_text(
                    f"${tx.price} | {tx.quantity} | {tx.buyer.name[:8]} | {tx.seller.name[:8]}", 
                    "small", 
                    self.colors["text"]["normal"]
                )
                tx_rect.topleft = (x + 10, y)
                self.screen.blit(tx_text, tx_rect)
                y += line_height
                
    def _render_simulation_details(self, panel_rect: Rect, text_renderer: TextRenderer) -> None:
        """Render simulation-wide information."""
        if not self.simulation:
            return
            
        simulation = self.simulation
        x, y = panel_rect.x + 20, panel_rect.y + 20
        line_height = 30
        
        # Current turn
        turn_text, turn_rect = text_renderer.render_text(
            f"Current Turn: {simulation.current_turn}", "normal", self.colors["text"]["normal"]
        )
        turn_rect.topleft = (x, y)
        self.screen.blit(turn_text, turn_rect)
        y += line_height
        
        # Planet count
        planet_count_text, planet_count_rect = text_renderer.render_text(
            f"Planets: {len(simulation.planets)}", "normal", self.colors["text"]["normal"]
        )
        planet_count_rect.topleft = (x, y)
        self.screen.blit(planet_count_text, planet_count_rect)
        y += line_height
        
        # Total actors
        total_actors = sum(len(planet.actors) for planet in simulation.planets)
        actors_text, actors_rect = text_renderer.render_text(
            f"Total Actors: {total_actors}", "normal", self.colors["text"]["normal"]
        )
        actors_rect.topleft = (x, y)
        self.screen.blit(actors_text, actors_rect)
        y += line_height
        
        # Total ships
        total_ships = len(simulation.ships)
        ships_text, ships_rect = text_renderer.render_text(
            f"Total Ships: {total_ships}", "normal", self.colors["text"]["normal"]
        )
        ships_rect.topleft = (x, y)
        self.screen.blit(ships_text, ships_rect)
        y += line_height
        
        # Ships in transit
        transit_count = sum(1 for ship in simulation.ships if ship.status == ShipStatus.TRAVELING)
        if transit_count > 0:
            transit_text, transit_rect = text_renderer.render_text(
                f"Ships in Transit: {transit_count}", "normal", self.colors["ship"]["in_transit"]
            )
            transit_rect.topleft = (x + 20, y)
            self.screen.blit(transit_text, transit_rect)
            y += line_height
            
        y += line_height
        
        # Economy overview
        economy_title, economy_title_rect = text_renderer.render_text(
            "Economy Overview:", "normal", self.colors["text"]["header"]
        )
        economy_title_rect.topleft = (x, y)
        self.screen.blit(economy_title, economy_title_rect)
        y += line_height
        
        # Calculate total money and food in the system
        total_money = 0
        total_food = 0
        raw_food_id = "raw_food"  # ID of the raw food commodity
        for planet in simulation.planets:
            for actor in planet.actors:
                total_money += actor.money
                if hasattr(actor, "inventory") and hasattr(actor.inventory, "commodities"):
                    for commodity in actor.inventory.commodities:
                        if commodity.id == raw_food_id:
                            total_food += actor.inventory.get_quantity(commodity)
                            break
        
        money_text, money_rect = text_renderer.render_text(
            f"• Total Money: ${total_money:,}", "normal", self.colors["text"]["money"]
        )
        money_rect.topleft = (x + 10, y)
        self.screen.blit(money_text, money_rect)
        y += line_height
        
        food_text, food_rect = text_renderer.render_text(
            f"• Total Food: {total_food}", "normal", self.colors["text"]["food"]
        )
        food_rect.topleft = (x + 10, y)
        self.screen.blit(food_text, food_rect)