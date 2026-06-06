from typing import TYPE_CHECKING, List, Optional

from spacesim2.core.actor import Actor
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
    from spacesim2.core.commodity import CommodityDefinition
    from spacesim2.core.market import Market
    from spacesim2.core.process import ProcessDefinition


class ColonistBrain(ActorBrain):
    """Decision-making logic for regular colonist actors."""

    def decide_economic_action(self, actor: Actor) -> Optional[EconomicCommand]:
        """Decide which economic action to take this turn."""
        # First, try to satisfy basic needs (food, clothing, shelter)
        registry = actor.sim.commodity_registry

        food_commodity = registry.get_commodity("food")
        biomass_commodity = registry.get_commodity("biomass")
        clothing_commodity = registry.get_commodity("clothing")
        fiber_commodity = registry.get_commodity("fiber")
        wood_commodity = registry.get_commodity("wood")

        if not food_commodity or not biomass_commodity:
            return GovernmentWorkCommand()

        # Check food needs first (most urgent)
        food_quantity = actor.inventory.get_quantity(food_commodity)
        if food_quantity < 5:
            # Try to make food
            if actor.can_execute_process("make_food"):
                return ProcessCommand("make_food")

            # If can't make food directly, try to gather biomass
            biomass_quantity = actor.inventory.get_quantity(biomass_commodity)
            if biomass_quantity < 4 and actor.can_execute_process("gather_biomass"):
                return ProcessCommand("gather_biomass")

        # Check clothing needs
        if clothing_commodity and fiber_commodity:
            clothing_quantity = actor.inventory.get_quantity(clothing_commodity)
            if clothing_quantity < 3:
                # Try to make clothing
                if actor.can_execute_process("make_clothing"):
                    return ProcessCommand("make_clothing")

                # If can't make clothing, try to gather fiber
                fiber_quantity = actor.inventory.get_quantity(fiber_commodity)
                if fiber_quantity < 4 and actor.can_execute_process("gather_fiber"):
                    return ProcessCommand("gather_fiber")

        # Check shelter needs (wood or metal)
        if wood_commodity:
            wood_quantity = actor.inventory.get_quantity(wood_commodity)
            if wood_quantity < 2 and actor.can_execute_process("harvest_wood"):
                return ProcessCommand("harvest_wood")

        # Check tool needs - prioritize having tools for productive work
        tools_commodity = registry.get_commodity("simple_tools")
        if tools_commodity:
            tools_quantity = actor.inventory.get_quantity(tools_commodity)
            if tools_quantity < 2:
                # Check if buying tools would be cheaper than making them
                market = actor.planet.market if actor.planet else None
                should_make_tools = True

                if market:
                    willingness_to_pay = self._calculate_tool_willingness_to_pay(actor)
                    bid, ask = market.get_bid_ask_spread(tools_commodity)

                    # If tools are available at a price at or below our willingness to pay,
                    # skip making - we'll buy in the market phase instead
                    if ask is not None and ask <= willingness_to_pay:
                        should_make_tools = False

                if should_make_tools and actor.can_execute_process("make_simple_tools"):
                    return ProcessCommand("make_simple_tools")

        # Try to find the most profitable process
        market = actor.planet.market if actor.planet else None
        if market:
            best_process = self._find_most_profitable_process(actor, market)

            # Return the most profitable process if better than government work
            if best_process and actor.can_execute_process(best_process.id):
                return ProcessCommand(best_process.id)

        # If no processes can be executed, do government work
        return GovernmentWorkCommand()

    def _find_most_profitable_process(
        self, actor: Actor, market: "Market"
    ) -> Optional["ProcessDefinition"]:
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

    def _calculate_turn_opportunity_cost(self, actor: Actor) -> int:
        """Calculate the opportunity cost of spending a turn making tools.

        This is the profit from the actor's next-best economic action.
        Returns GOVERNMENT_WAGE (10) as a minimum floor.
        """
        GOVERNMENT_WAGE = 10

        market = actor.planet.market if actor.planet else None
        if not market:
            return GOVERNMENT_WAGE

        best_process = self._find_most_profitable_process(actor, market)
        if not best_process:
            return GOVERNMENT_WAGE

        # Calculate profit of best process (same logic as _find_most_profitable_process)
        input_cost = 0
        for commodity, quantity in best_process.inputs.items():
            bid, ask = market.get_bid_ask_spread(commodity)
            price = ask if ask is not None else market.get_avg_price(commodity)
            input_cost += price * quantity

        output_value = 0
        for commodity, quantity in best_process.outputs.items():
            bid, ask = market.get_bid_ask_spread(commodity)
            price = bid if bid is not None else market.get_avg_price(commodity)
            output_value += price * quantity

        profit = output_value - input_cost
        return max(GOVERNMENT_WAGE, int(profit))

    def _calculate_tool_willingness_to_pay(self, actor: Actor) -> int:
        """Calculate maximum price actor would pay for a tool.

        Formula: cost_to_make_inputs + opportunity_cost_of_turn

        Where:
        - cost_to_make_inputs = market ask price for 2 common_metal
        - opportunity_cost_of_turn = profit from next-best action (or govt work)
        """
        market = actor.planet.market if actor.planet else None
        if not market:
            return 0  # Cannot determine willingness without market

        # Cost of inputs to make tools (2 common_metal per processes.yaml)
        common_metal = actor.sim.commodity_registry.get_commodity("common_metal")
        if not common_metal:
            return 0

        bid, ask = market.get_bid_ask_spread(common_metal)
        metal_price = ask if ask is not None else market.get_avg_price(common_metal)
        input_cost = int(metal_price * 2)  # make_simple_tools requires 2 common_metal

        # Opportunity cost of spending a turn making tools
        opportunity_cost = self._calculate_turn_opportunity_cost(actor)

        return input_cost + opportunity_cost

    def decide_market_actions(self, actor: "Actor") -> List[MarketCommand]:
        """Regular actors buy what they need and sell excess, matching existing orders when possible."""
        if not actor.planet:
            return []

        market = actor.planet.market
        commands: List[MarketCommand] = []

        # Get existing actor's orders
        existing_orders = market.get_actor_orders(actor)

        # Cancel all existing orders
        for order in existing_orders["buy"] + existing_orders["sell"]:
            commands.append(CancelOrderCommand(order.order_id))

        # Define minimum inventory levels for needs-related commodities
        min_keep_levels = {
            "food": 6,
            "clothing": 3,
            "wood": 2,  # shelter material
            "common_metal": 2,  # shelter material
            "simple_tools": 2,  # tools for production
        }

        # Trade all transportable commodities
        for commodity in actor.sim.commodity_registry.all_commodities():
            if not commodity.transportable:
                continue
            min_keep = min_keep_levels.get(commodity.id, 0)
            trade_commands = self._get_trade_commands(
                actor, market, commodity, min_keep=min_keep
            )
            commands.extend(trade_commands)

        return commands

    def _get_trade_commands(
        self,
        actor: Actor,
        market: "Market",
        commodity_type: "CommodityDefinition",
        min_keep: int = 0,
    ) -> List[MarketCommand]:
        """Helper method to generate trading commands for a specific commodity.

        Args:
            market: The market to trade in
            commodity_type: The type of commodity to trade
            min_keep: Minimum amount to keep in inventory

        Returns:
            List of MarketCommand objects for trading actions
        """
        commands: List[MarketCommand] = []

        # Track inventory
        quantity = actor.inventory.get_quantity(commodity_type)
        available_inventory = actor.inventory.get_available_quantity(commodity_type)

        # Handle buying if we're below our minimum
        if quantity < min_keep:
            # Calculate how much we need
            quantity_to_buy = min_keep - quantity

            # Get existing sell orders in the market (excluding our own)
            market_sell_orders = sorted(
                [
                    o
                    for o in market.sell_orders.get(commodity_type, [])
                    if o.actor != actor
                ],
                key=lambda o: (o.price, o.timestamp),  # Sort by price (lowest first)
            )

            # For tools, calculate willingness to pay based on opportunity cost
            max_price = None
            if commodity_type.id == "simple_tools":
                max_price = self._calculate_tool_willingness_to_pay(actor)

            if market_sell_orders:
                # Start with the lowest price sell order
                best_sell_order = market_sell_orders[0]
                buy_price = best_sell_order.price

                # For tools, only buy if price is at or below willingness to pay
                if max_price is not None and buy_price > max_price:
                    pass  # Don't buy - too expensive
                else:
                    # Check if we can afford it
                    max_affordable_quantity = min(
                        quantity_to_buy, actor.money // buy_price
                    )

                    if max_affordable_quantity > 0:
                        # Place a matching buy order at exactly the seller's price
                        commands.append(
                            PlaceBuyOrderCommand(
                                commodity_type, max_affordable_quantity, buy_price
                            )
                        )

            elif max_price is not None and max_price > 0:
                # No sell orders exist, but for tools we can place a bid at our
                # willingness to pay. This expresses demand and can cross with
                # market maker orders in the matching phase.
                max_affordable_quantity = min(quantity_to_buy, actor.money // max_price)

                if max_affordable_quantity > 0:
                    commands.append(
                        PlaceBuyOrderCommand(
                            commodity_type, max_affordable_quantity, max_price
                        )
                    )

        # Handle selling if we have excess
        if available_inventory > min_keep:
            # Calculate how much we can sell
            quantity_to_sell = available_inventory - min_keep

            # Get existing buy orders in the market (excluding our own)
            market_buy_orders = sorted(
                [
                    o
                    for o in market.buy_orders.get(commodity_type, [])
                    if o.actor != actor
                ],
                key=lambda o: (-o.price, o.timestamp),  # Sort by price (highest first)
            )

            # Check if there are any buy orders available
            if market_buy_orders:
                # Start with the highest price buy order
                best_buy_order = market_buy_orders[0]

                # Accept any price - regular actors are price takers
                # Place a matching sell order at exactly the buyer's price
                commands.append(
                    PlaceSellOrderCommand(
                        commodity_type, quantity_to_sell, best_buy_order.price
                    )
                )

        return commands
