from typing import Optional, List, TYPE_CHECKING

from spacesim2.core.actor import Actor
from spacesim2.core.actor_brain import ActorBrain
from spacesim2.core.commands import EconomicCommand, MarketCommand, ProcessCommand, GovernmentWorkCommand, CancelOrderCommand, PlaceBuyOrderCommand, PlaceSellOrderCommand

if TYPE_CHECKING:
    from spacesim2.core.process import ProcessDefinition


class ColonistBrain(ActorBrain):
    """Decision-making logic for regular colonist actors."""
    
    def decide_economic_action(self, actor:Actor) -> Optional[EconomicCommand]:
        """Decide which economic action to take this turn."""
        # First, try to satisfy basic needs (food)
        # Actor always has sim reference
            
        food_commodity = actor.sim.commodity_registry.get_commodity("food")
        biomass_commodity = actor.sim.commodity_registry.get_commodity("biomass")
        
        if not food_commodity or not biomass_commodity:
            return GovernmentWorkCommand()
            
        food_quantity = actor.inventory.get_quantity(food_commodity)
        if food_quantity < 5:
            # Try to make food
            if actor.can_execute_process("make_food"):
                return ProcessCommand("make_food")
                
            # If can't make food directly, try to gather biomass
            biomass_quantity = actor.inventory.get_quantity(biomass_commodity)
            if biomass_quantity < 2 and actor.can_execute_process("gather_biomass"):
                return ProcessCommand("gather_biomass")

        # Try to find the most profitable process
        market = actor.planet.market if actor.planet else None
        if market:
            best_process = self._find_most_profitable_process(actor, market)
            
            # Return the most profitable process if better than government work
            if best_process and actor.can_execute_process(best_process.id):
                return ProcessCommand(best_process.id)
        
        # If no processes can be executed, do government work
        return GovernmentWorkCommand()
    
    def _find_most_profitable_process(self, actor:Actor, market) -> Optional['ProcessDefinition']:
        """Find the most profitable process based on current market prices and available resources."""
        # Actor always has sim reference

        best_process = None
        best_profit = 10  # Must exceed government work profit

        for process in actor.sim.process_registry.all_processes():
            # Calculate potential profit using actual market bid/ask prices
            input_cost = 0
            for commodity, quantity in process.inputs.items():
                # Use ask price (what we'd pay to buy) if available
                bid, ask = market.get_bid_ask_spread(commodity)
                price = ask if ask is not None else market.get_avg_price(commodity)
                input_cost += price * quantity

            output_value = 0
            for commodity, quantity in process.outputs.items():
                # Use bid price (what buyers will pay) if available
                bid, ask = market.get_bid_ask_spread(commodity)
                price = bid if bid is not None else market.get_avg_price(commodity)
                output_value += price * quantity

            potential_profit = output_value - input_cost

            # Check if we can execute this process
            can_execute = actor.can_execute_process(process.id)

            if can_execute and potential_profit > best_profit:
                best_process = process
                best_profit = potential_profit

        return best_process
    
    def decide_market_actions(self, actor:'Actor') -> List[MarketCommand]:
        """Regular actors buy what they need and sell excess, matching existing orders when possible."""
        if not actor.planet:
            return []
        
        market = actor.planet.market
        commands = []
        
        # Get existing actor's orders
        existing_orders = market.get_actor_orders(actor)
        
        # Cancel all existing orders
        for order in existing_orders["buy"] + existing_orders["sell"]:
            commands.append(CancelOrderCommand(order.order_id))
        
        # Get commodity references
        # Actor always has sim reference
        food_commodity = actor.sim.commodity_registry["food"]
        fuel_commodity = actor.sim.commodity_registry["nova_fuel"]
        fuel_ore_commodity = actor.sim.commodity_registry["nova_fuel_ore"]
        wood_commodity = actor.sim.commodity_registry["wood"]
        common_metal_commodity = actor.sim.commodity_registry["common_metal"]
        common_metal_ore_commodity = actor.sim.commodity_registry["common_metal_ore"]

        # Handle food trading
        food_commands = self._get_trade_commands(actor, market, food_commodity, min_keep=6)
        commands.extend(food_commands)

        # Handle fuel trading - we don't need to keep any fuel for ourselves
        fuel_commands = self._get_trade_commands(actor, market, fuel_commodity, min_keep=0)
        commands.extend(fuel_commands)

        # Handle fuel ore trading - sell excess ore we mine
        fuel_ore_commands = self._get_trade_commands(actor, market, fuel_ore_commodity, min_keep=0)
        commands.extend(fuel_ore_commands)

        # Handle shelter material trading
        wood_commands = self._get_trade_commands(actor, market, wood_commodity, min_keep=0)
        commands.extend(wood_commands)

        common_metal_commands = self._get_trade_commands(actor, market, common_metal_commodity, min_keep=0)
        commands.extend(common_metal_commands)

        common_metal_ore_commands = self._get_trade_commands(actor, market, common_metal_ore_commodity, min_keep=0)
        commands.extend(common_metal_ore_commands)

        return commands
    
    def _get_trade_commands(self, actor:Actor, market, commodity_type, min_keep=0) -> List[MarketCommand]:
        """Helper method to generate trading commands for a specific commodity.
        
        Args:
            market: The market to trade in
            commodity_type: The type of commodity to trade
            min_keep: Minimum amount to keep in inventory
            
        Returns:
            List of MarketCommand objects for trading actions
        """
        commands = []
        
        # Track inventory
        quantity = actor.inventory.get_quantity(commodity_type)
        available_inventory = actor.inventory.get_available_quantity(commodity_type)
        
        # Handle buying if we're below our minimum
        if quantity < min_keep:
            # Calculate how much we need
            quantity_to_buy = min_keep - quantity
            
            # Get existing sell orders in the market (excluding our own)
            market_sell_orders = sorted(
                [o for o in market.sell_orders.get(commodity_type, []) if o.actor != actor],
                key=lambda o: (o.price, o.timestamp)  # Sort by price (lowest first)
            )
            
            # Check if there are any sell orders available
            if market_sell_orders:
                # Start with the lowest price sell order
                best_sell_order = market_sell_orders[0]
                
                # Check if we can afford it
                max_affordable_quantity = min(
                    quantity_to_buy,
                    actor.money // best_sell_order.price
                )
                
                if max_affordable_quantity > 0:
                    # Place a matching buy order at exactly the seller's price
                    commands.append(PlaceBuyOrderCommand(
                        commodity_type, max_affordable_quantity, best_sell_order.price
                    ))
        
        # Handle selling if we have excess
        if available_inventory > min_keep:
            # Calculate how much we can sell
            quantity_to_sell = available_inventory - min_keep
            
            # Get existing buy orders in the market (excluding our own)
            market_buy_orders = sorted(
                [o for o in market.buy_orders.get(commodity_type, []) if o.actor != actor],
                key=lambda o: (-o.price, o.timestamp)  # Sort by price (highest first)
            )
            
            # Check if there are any buy orders available
            if market_buy_orders:
                # Start with the highest price buy order
                best_buy_order = market_buy_orders[0]
                
                # Accept any price - regular actors are price takers
                # Place a matching sell order at exactly the buyer's price
                commands.append(PlaceSellOrderCommand(
                    commodity_type, quantity_to_sell, best_buy_order.price
                ))
        
        return commands