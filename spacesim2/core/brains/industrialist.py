import random
from typing import Optional, List, TYPE_CHECKING

from spacesim2.core.actor_brain import ActorBrain
from spacesim2.core.commands import EconomicCommand, MarketCommand, ProcessCommand, GovernmentWorkCommand, CancelOrderCommand, PlaceBuyOrderCommand, PlaceSellOrderCommand

if TYPE_CHECKING:
    from spacesim2.core.process import ProcessDefinition
    from spacesim2.core.actor import Actor


class IndustrialistBrain(ActorBrain):
    """Decision-making logic for industrialist actors who specialize in production."""
    
    def __init__(self):
        self.chosen_recipe_id: Optional[str] = None
        self.turns_since_recipe_evaluation: int = 0
        
    def decide_economic_action(self, actor: 'Actor') -> Optional[EconomicCommand]:
        """Decide which economic action to take this turn."""
        # First check if we need to re-evaluate our recipe (1% chance per turn)
        self.turns_since_recipe_evaluation += 1
        if self._should_reevaluate_recipe():
            self.chosen_recipe_id = self._select_new_recipe(actor)
            self.turns_since_recipe_evaluation = 0
            
        # If we don't have a recipe yet, select one
        if not self.chosen_recipe_id:
            self.chosen_recipe_id = self._select_new_recipe(actor)
            self.turns_since_recipe_evaluation = 0
        
        # Handle basic needs first - try to buy food from market
        food_commodity = actor.sim.commodity_registry.get_commodity("food")
        if not food_commodity:
            return GovernmentWorkCommand()
            
        food_quantity = actor.inventory.get_quantity(food_commodity)
        if food_quantity < 5:
            # Try to buy food from market first - this is handled in market actions
            # If we still need food after market actions, we'll try to make it
            if food_quantity < 2:  # Critical food shortage
                # Try to make food ourselves as emergency
                if actor.can_execute_process("make_food"):
                    return ProcessCommand("make_food")
                # Try to gather biomass for food production
                biomass_commodity = actor.sim.commodity_registry.get_commodity("biomass")
                if biomass_commodity:
                    biomass_quantity = actor.inventory.get_quantity(biomass_commodity)
                    if biomass_quantity < 4 and actor.can_execute_process("gather_biomass"):
                        return ProcessCommand("gather_biomass")
        
        # Try to execute our chosen recipe
        if self.chosen_recipe_id and actor.can_execute_process(self.chosen_recipe_id):
            return ProcessCommand(self.chosen_recipe_id)
        
        # If we can't execute our recipe, fall back to government work
        return GovernmentWorkCommand()
    
    def decide_market_actions(self, actor: 'Actor') -> List[MarketCommand]:
        """Market actions focused on buying personal needs and recipe inputs, selling outputs."""
        if not actor.planet:
            return []
        
        market = actor.planet.market
        commands = []
        
        # Get existing orders and cancel them
        existing_orders = market.get_actor_orders(actor)
        for order in existing_orders["buy"] + existing_orders["sell"]:
            commands.append(CancelOrderCommand(order.order_id))
        
        # 1. Buy food for personal consumption (market-first approach)
        food_commodity = actor.sim.commodity_registry.get_commodity("food")
        if food_commodity:
            food_commands = self._get_food_purchase_commands(actor, market, food_commodity)
            commands.extend(food_commands)
        
        # 2. Handle recipe-related trading
        if self.chosen_recipe_id:
            recipe_commands = self._get_recipe_trading_commands(actor, market)
            commands.extend(recipe_commands)
        
        return commands
    
    def _should_reevaluate_recipe(self) -> bool:
        """1% chance per turn to re-evaluate recipe choice."""
        return random.random() < 0.01
    
    def _select_new_recipe(self, actor: 'Actor') -> Optional[str]:
        """Select a new recipe based on market viability."""
        if not actor.planet:
            return None
            
        market = actor.planet.market
        viable_recipes = []
        
        for process in actor.sim.process_registry.all_processes():
            if self._is_recipe_viable(actor, market, process):
                viable_recipes.append(process.id)
        
        if viable_recipes:
            return random.choice(viable_recipes)
        return None
    
    def _is_recipe_viable(self, actor: 'Actor', market, process: 'ProcessDefinition') -> bool:
        """Check if a recipe is economically viable given current market conditions."""
        # Calculate input costs based on actual market ask prices
        total_input_cost = 0
        for commodity, quantity in process.inputs.items():
            # Use ask price (what we'd pay to buy) if available
            bid, ask = market.get_bid_ask_spread(commodity)
            if ask is not None:
                price = ask
            else:
                # Fall back to avg price, but require some market activity
                price = market.get_avg_price(commodity)
                if price <= 0:
                    return False
            total_input_cost += price * quantity

        # Calculate output value based on actual market bid prices
        total_output_value = 0
        for commodity, quantity in process.outputs.items():
            # Use bid price (what buyers will pay) if available
            bid, ask = market.get_bid_ask_spread(commodity)
            if bid is not None:
                price = bid
            else:
                # Fall back to avg price, but require some market activity
                price = market.get_avg_price(commodity)
                if price <= 0:
                    return False
            total_output_value += price * quantity

        # Recipe is viable if profit margin is at least 20% above input costs
        min_required_value = total_input_cost * 1.2
        return total_output_value >= min_required_value
    
    def _get_food_purchase_commands(self, actor: 'Actor', market, food_commodity) -> List[MarketCommand]:
        """Generate commands to buy food for personal consumption."""
        commands = []
        
        food_quantity = actor.inventory.get_quantity(food_commodity)
        food_target = 6  # Target inventory level
        
        if food_quantity < food_target:
            quantity_to_buy = food_target - food_quantity
            
            # Get available sell orders for food
            market_sell_orders = sorted(
                [o for o in market.sell_orders.get(food_commodity, []) if o.actor != actor],
                key=lambda o: (o.price, o.timestamp)
            )
            
            if market_sell_orders:
                best_sell_order = market_sell_orders[0]
                max_affordable = min(
                    quantity_to_buy,
                    actor.money // best_sell_order.price
                )
                
                if max_affordable > 0:
                    commands.append(PlaceBuyOrderCommand(
                        food_commodity, max_affordable, best_sell_order.price
                    ))
        
        return commands
    
    def _get_recipe_trading_commands(self, actor: 'Actor', market) -> List[MarketCommand]:
        """Generate trading commands for recipe inputs and outputs."""
        commands = []
        
        process = actor.sim.process_registry.get_process(self.chosen_recipe_id)
        if not process:
            return commands
        
        # Buy inputs for recipe
        for commodity, needed_quantity in process.inputs.items():
            current_quantity = actor.inventory.get_quantity(commodity)
            if current_quantity < needed_quantity:
                quantity_to_buy = needed_quantity - current_quantity
                
                market_sell_orders = sorted(
                    [o for o in market.sell_orders.get(commodity, []) if o.actor != actor],
                    key=lambda o: (o.price, o.timestamp)
                )
                
                if market_sell_orders:
                    best_sell_order = market_sell_orders[0]
                    max_affordable = min(
                        quantity_to_buy,
                        actor.money // best_sell_order.price
                    )
                    
                    if max_affordable > 0:
                        commands.append(PlaceBuyOrderCommand(
                            commodity, max_affordable, best_sell_order.price
                        ))
        
        # Sell outputs from recipe
        for commodity, _ in process.outputs.items():
            available_quantity = actor.inventory.get_available_quantity(commodity)
            if available_quantity > 0:
                market_buy_orders = sorted(
                    [o for o in market.buy_orders.get(commodity, []) if o.actor != actor],
                    key=lambda o: (-o.price, o.timestamp)
                )
                
                if market_buy_orders:
                    best_buy_order = market_buy_orders[0]
                    commands.append(PlaceSellOrderCommand(
                        commodity, available_quantity, best_buy_order.price
                    ))
        
        return commands