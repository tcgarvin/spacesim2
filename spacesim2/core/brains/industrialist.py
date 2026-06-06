import random
from typing import TYPE_CHECKING, List, Optional

from spacesim2.core.actor_brain import ActorBrain
from spacesim2.core.commands import (
    CancelOrderCommand,
    EconomicCommand,
    GovernmentWorkCommand,
    MarketCommand,
    PlaceBuyOrderCommand,
    PlaceSellOrderCommand,
    ProcessCommand,
)

if TYPE_CHECKING:
    from spacesim2.core.actor import Actor
    from spacesim2.core.commodity import CommodityDefinition
    from spacesim2.core.market import Market
    from spacesim2.core.process import ProcessDefinition


class IndustrialistBrain(ActorBrain):
    """Decision-making logic for industrialist actors who specialize in production."""

    def __init__(self) -> None:
        self.chosen_recipe_id: Optional[str] = None
        self.turns_since_recipe_evaluation: int = 0

    def decide_economic_action(self, actor: "Actor") -> Optional[EconomicCommand]:
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

        registry = actor.sim.commodity_registry

        # Handle critical needs - food, clothing, shelter
        food_commodity = registry.get_commodity("food")
        biomass_commodity = registry.get_commodity("biomass")
        clothing_commodity = registry.get_commodity("clothing")
        fiber_commodity = registry.get_commodity("fiber")

        if not food_commodity:
            return GovernmentWorkCommand()

        # Critical food shortage - handle before recipe work
        food_quantity = actor.inventory.get_quantity(food_commodity)
        if food_quantity < 2:
            if actor.can_execute_process("make_food"):
                return ProcessCommand("make_food")
            if biomass_commodity:
                biomass_quantity = actor.inventory.get_quantity(biomass_commodity)
                if biomass_quantity < 4 and actor.can_execute_process("gather_biomass"):
                    return ProcessCommand("gather_biomass")

        # Critical clothing shortage
        if clothing_commodity and fiber_commodity:
            clothing_quantity = actor.inventory.get_quantity(clothing_commodity)
            if clothing_quantity < 1:
                if actor.can_execute_process("make_clothing"):
                    return ProcessCommand("make_clothing")
                fiber_quantity = actor.inventory.get_quantity(fiber_commodity)
                if fiber_quantity < 4 and actor.can_execute_process("gather_fiber"):
                    return ProcessCommand("gather_fiber")

        # Check if our chosen recipe needs facilities/tools we lack
        if self.chosen_recipe_id:
            process = actor.sim.process_registry.get_process(self.chosen_recipe_id)
            if process:
                # Check for missing facilities and try to build them
                for facility in process.facilities_required:
                    if not actor.inventory.has_quantity(facility, 1):
                        build_process_id = self._get_build_process_for_facility(
                            facility
                        )
                        if build_process_id and actor.can_execute_process(
                            build_process_id
                        ):
                            return ProcessCommand(build_process_id)

                # Check for missing tools and try to make them
                for tool in process.tools_required:
                    if not actor.inventory.has_quantity(tool, 1):
                        if actor.can_execute_process("make_simple_tools"):
                            return ProcessCommand("make_simple_tools")

        # Try to execute our chosen recipe
        if self.chosen_recipe_id and actor.can_execute_process(self.chosen_recipe_id):
            return ProcessCommand(self.chosen_recipe_id)

        # If we can't execute our recipe, fall back to government work
        return GovernmentWorkCommand()

    def decide_market_actions(self, actor: "Actor") -> List[MarketCommand]:
        """Market actions focused on buying personal needs and recipe inputs, selling outputs."""
        if not actor.planet:
            return []

        market = actor.planet.market
        commands: List[MarketCommand] = []

        # Get existing orders and cancel them
        existing_orders = market.get_actor_orders(actor)
        for order in existing_orders["buy"] + existing_orders["sell"]:
            commands.append(CancelOrderCommand(order.order_id))

        # 1. Buy food for personal consumption (market-first approach)
        food_commodity = actor.sim.commodity_registry.get_commodity("food")
        if food_commodity:
            food_commands = self._get_food_purchase_commands(
                actor, market, food_commodity
            )
            commands.extend(food_commands)

        # 2. Handle recipe-related trading
        if self.chosen_recipe_id:
            recipe_commands = self._get_recipe_trading_commands(actor, market)
            commands.extend(recipe_commands)

        return commands

    def _should_reevaluate_recipe(self) -> bool:
        """1% chance per turn to re-evaluate recipe choice."""
        return random.random() < 0.01

    def _get_build_process_for_facility(
        self, facility: "CommodityDefinition"
    ) -> Optional[str]:
        """Map facility commodities to their build processes."""
        facility_to_process = {
            "smelting_facility": "build_smelting_facility",
            "metalworking_facility": "build_metalworking_facility",
            "textile_mill": "build_textile_mill",
            "chemistry_lab": "build_chemistry_lab",
            "precision_forge": "build_precision_forge",
            "electronics_workshop": "build_electronics_workshop",
            "advanced_factory": "build_advanced_factory",
        }
        return facility_to_process.get(facility.id)

    def _select_new_recipe(self, actor: "Actor") -> Optional[str]:
        """Select a new recipe based on market viability and expected profit.

        Weights recipes by expected profit margin, preferring more profitable ones.
        This causes industrialists to specialize in what their planet is good at.
        """
        if not actor.planet:
            return None

        market = actor.planet.market
        recipe_scores: list[tuple[str, float]] = []

        for process in actor.sim.process_registry.all_processes():
            score = self._calculate_recipe_score(actor, market, process)
            if score > 0:
                recipe_scores.append((process.id, score))

        if not recipe_scores:
            return None

        # Weighted random selection based on score
        # Higher scores = more likely to be chosen
        total_score = sum(score for _, score in recipe_scores)
        if total_score <= 0:
            return None

        roll = random.random() * total_score
        cumulative = 0.0
        for process_id, score in recipe_scores:
            cumulative += score
            if roll <= cumulative:
                return process_id

        # Fallback (shouldn't reach here)
        return recipe_scores[-1][0]

    def _calculate_recipe_score(
        self, actor: "Actor", market: "Market", process: "ProcessDefinition"
    ) -> float:
        """Calculate a profitability score for a recipe.

        Returns expected profit margin as a score. Higher = more profitable.
        Returns 0 if recipe is not viable.
        """
        # Calculate input costs
        total_input_cost = 0.0
        for commodity, quantity in process.inputs.items():
            bid, ask = market.get_bid_ask_spread(commodity)
            if ask is not None:
                price = ask
            else:
                price = market.get_avg_price(commodity)
                if price <= 0:
                    return 0.0
            total_input_cost += price * quantity

        # Factor in tool costs (amortized over expected lifespan of 100 uses)
        TOOL_EXPECTED_LIFESPAN = 100
        for tool in process.tools_required:
            if not actor.inventory.has_quantity(tool, 1):
                # Need to acquire tool - check if actually available in market
                bid, ask = market.get_bid_ask_spread(tool)
                if ask is None:
                    # No sellers for required tools - recipe not viable unless
                    # actor can make tools themselves
                    metalworking = actor.sim.commodity_registry.get_commodity(
                        "metalworking_facility"
                    )
                    if metalworking and actor.inventory.has_quantity(metalworking, 1):
                        # Actor can make tools - estimate cost from tool process
                        tool_process = actor.sim.process_registry.get_process(
                            "make_simple_tools"
                        )
                        if tool_process:
                            tool_input_cost = 0.0
                            for commodity, qty in tool_process.inputs.items():
                                _, inp_ask = market.get_bid_ask_spread(commodity)
                                inp_price = (
                                    inp_ask
                                    if inp_ask is not None
                                    else market.get_avg_price(commodity)
                                )
                                if inp_price <= 0:
                                    return 0.0
                                tool_input_cost += inp_price * qty
                            total_input_cost += tool_input_cost / TOOL_EXPECTED_LIFESPAN
                        else:
                            return 0.0
                    else:
                        return 0.0  # Can't buy tools and can't make them
                else:
                    total_input_cost += ask / TOOL_EXPECTED_LIFESPAN

        # Check facility requirements - factor in cost of building if needed
        FACILITY_EXPECTED_LIFESPAN = 500  # Facilities are durable
        for facility in process.facilities_required:
            if not actor.inventory.has_quantity(facility, 1):
                # Check if we can build the facility
                build_process_id = self._get_build_process_for_facility(facility)
                if not build_process_id:
                    return 0.0  # No way to get this facility

                build_process = actor.sim.process_registry.get_process(build_process_id)
                if not build_process:
                    return 0.0

                # Calculate cost to build the facility
                facility_build_cost = 0.0
                for inp_commodity, inp_qty in build_process.inputs.items():
                    _, inp_ask = market.get_bid_ask_spread(inp_commodity)
                    inp_price = (
                        inp_ask
                        if inp_ask is not None
                        else market.get_avg_price(inp_commodity)
                    )
                    if inp_price <= 0:
                        return 0.0  # Can't get inputs for facility
                    facility_build_cost += inp_price * inp_qty

                # Amortize facility cost over expected lifespan
                total_input_cost += facility_build_cost / FACILITY_EXPECTED_LIFESPAN

        # Determine planet attribute modifier
        attribute_modifier = 1.0
        if process.resource_attribute and actor.planet and actor.planet.attributes:
            attr_value = actor.planet.attributes.get_availability(
                process.resource_attribute.commodity
            )
            attribute_modifier = attr_value

        # Calculate expected output value
        total_output_value = 0.0
        for commodity, quantity in process.outputs.items():
            # Non-transportable outputs (facilities) are for personal use, not sale
            # Give them notional value based on what recipes they enable
            if not commodity.transportable:
                # Facilities have intrinsic value for enabling other recipes
                # Use a notional value based on input cost (building a facility is worthwhile
                # if the inputs cost less than what the facility enables)
                FACILITY_NOTIONAL_VALUE = 50.0
                total_output_value += FACILITY_NOTIONAL_VALUE * quantity
                continue

            bid, ask = market.get_bid_ask_spread(commodity)
            if bid is not None:
                price = bid
            else:
                price = market.get_avg_price(commodity)
                if price <= 0:
                    return 0.0
            expected_quantity = quantity * attribute_modifier
            total_output_value += price * expected_quantity

        # Require at least 20% margin
        min_required_value = total_input_cost * 1.2
        if total_output_value < min_required_value:
            return 0.0

        # Score is expected profit (output - input)
        # For gathering (no inputs), this is just expected output value
        return total_output_value - total_input_cost

    def _is_recipe_viable(
        self, actor: "Actor", market: "Market", process: "ProcessDefinition"
    ) -> bool:
        """Check if a recipe is economically viable given current market conditions.

        For processes with resource_attribute, adjusts expected output based on
        planet attributes to reflect actual expected yield.
        """
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

        # Determine planet attribute modifier for this process
        # This affects expected output for gathering/mining processes
        attribute_modifier = 1.0
        if process.resource_attribute and actor.planet and actor.planet.attributes:
            attr_value = actor.planet.attributes.get_availability(
                process.resource_attribute.commodity
            )
            # Both "success" and "output" effects reduce expected value proportionally
            # - "output": You get attr_value fraction of base output
            # - "success": You succeed attr_value fraction of the time
            attribute_modifier = attr_value

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
            # Apply attribute modifier to expected output
            expected_quantity = quantity * attribute_modifier
            total_output_value += price * expected_quantity

        # Recipe is viable if profit margin is at least 20% above input costs
        min_required_value = total_input_cost * 1.2
        return total_output_value >= min_required_value

    def _get_food_purchase_commands(
        self, actor: "Actor", market: "Market", food_commodity: "CommodityDefinition"
    ) -> List[MarketCommand]:
        """Generate commands to buy food for personal consumption."""
        commands: List[MarketCommand] = []

        food_quantity = actor.inventory.get_quantity(food_commodity)
        food_target = 6  # Target inventory level

        if food_quantity < food_target:
            quantity_to_buy = food_target - food_quantity

            # Get available sell orders for food
            market_sell_orders = sorted(
                [
                    o
                    for o in market.sell_orders.get(food_commodity, [])
                    if o.actor != actor
                ],
                key=lambda o: (o.price, o.timestamp),
            )

            if market_sell_orders:
                best_sell_order = market_sell_orders[0]
                max_affordable = min(
                    quantity_to_buy, actor.money // best_sell_order.price
                )

                if max_affordable > 0:
                    commands.append(
                        PlaceBuyOrderCommand(
                            food_commodity, max_affordable, best_sell_order.price
                        )
                    )

        return commands

    def _calculate_tool_willingness_to_pay(
        self, actor: "Actor", market: "Market"
    ) -> int:
        """Calculate max price industrialist would pay for a tool.

        For industrialists, willingness to pay is based on:
        - Input cost to make the tool (2 common_metal)
        - Opportunity cost of the turn (recipe profit or govt wage)
        """
        GOVERNMENT_WAGE = 10

        # Cost of inputs to make tools (2 common_metal)
        common_metal = actor.sim.commodity_registry.get_commodity("common_metal")
        if not common_metal:
            return GOVERNMENT_WAGE * 10  # Fallback

        bid, ask = market.get_bid_ask_spread(common_metal)
        metal_price = ask if ask is not None else market.get_avg_price(common_metal)
        input_cost = int(metal_price * 2)

        # Opportunity cost: recipe profit if we have one, else govt wage
        opportunity_cost = GOVERNMENT_WAGE
        if self.chosen_recipe_id:
            process = actor.sim.process_registry.get_process(self.chosen_recipe_id)
            if process:
                score = self._calculate_recipe_score(actor, market, process)
                if score > GOVERNMENT_WAGE:
                    opportunity_cost = int(score)

        return input_cost + opportunity_cost

    def _get_recipe_trading_commands(
        self, actor: "Actor", market: "Market"
    ) -> List[MarketCommand]:
        """Generate trading commands for recipe inputs and outputs."""
        commands: List[MarketCommand] = []

        process = actor.sim.process_registry.get_process(self.chosen_recipe_id)
        if not process:
            return commands

        # Calculate willingness to pay for tools upfront
        tool_willingness_to_pay = self._calculate_tool_willingness_to_pay(actor, market)

        # Buy required tools (maintain buffer of 2)
        TOOL_BUFFER = 2
        for tool in process.tools_required:
            current_quantity = actor.inventory.get_quantity(tool)
            if current_quantity < TOOL_BUFFER:
                quantity_to_buy = TOOL_BUFFER - current_quantity

                market_sell_orders = sorted(
                    [o for o in market.sell_orders.get(tool, []) if o.actor != actor],
                    key=lambda o: (o.price, o.timestamp),
                )

                if market_sell_orders:
                    best_sell_order = market_sell_orders[0]
                    # Only buy if price is at or below willingness to pay
                    if best_sell_order.price <= tool_willingness_to_pay:
                        max_affordable = min(
                            quantity_to_buy, actor.money // best_sell_order.price
                        )

                        if max_affordable > 0:
                            commands.append(
                                PlaceBuyOrderCommand(
                                    tool, max_affordable, best_sell_order.price
                                )
                            )
                elif tool_willingness_to_pay > 0:
                    # No sell orders - place bid at willingness to pay
                    max_affordable = min(
                        quantity_to_buy, actor.money // tool_willingness_to_pay
                    )

                    if max_affordable > 0:
                        commands.append(
                            PlaceBuyOrderCommand(
                                tool, max_affordable, tool_willingness_to_pay
                            )
                        )

        # Buy inputs for recipe
        for commodity, needed_quantity in process.inputs.items():
            current_quantity = actor.inventory.get_quantity(commodity)
            if current_quantity < needed_quantity:
                quantity_to_buy = needed_quantity - current_quantity

                market_sell_orders = sorted(
                    [
                        o
                        for o in market.sell_orders.get(commodity, [])
                        if o.actor != actor
                    ],
                    key=lambda o: (o.price, o.timestamp),
                )

                if market_sell_orders:
                    best_sell_order = market_sell_orders[0]
                    max_affordable = min(
                        quantity_to_buy, actor.money // best_sell_order.price
                    )

                    if max_affordable > 0:
                        commands.append(
                            PlaceBuyOrderCommand(
                                commodity, max_affordable, best_sell_order.price
                            )
                        )

        # Sell outputs from recipe
        for commodity, _ in process.outputs.items():
            available_quantity = actor.inventory.get_available_quantity(commodity)
            if available_quantity > 0:
                market_buy_orders = sorted(
                    [
                        o
                        for o in market.buy_orders.get(commodity, [])
                        if o.actor != actor
                    ],
                    key=lambda o: (-o.price, o.timestamp),
                )

                if market_buy_orders:
                    best_buy_order = market_buy_orders[0]
                    commands.append(
                        PlaceSellOrderCommand(
                            commodity, available_quantity, best_buy_order.price
                        )
                    )

        return commands
