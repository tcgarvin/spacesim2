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

        # Keep a wood buffer (raw input for tools and building materials)
        if wood_commodity:
            wood_quantity = actor.inventory.get_quantity(wood_commodity)
            if wood_quantity < 2 and actor.can_execute_process("harvest_wood"):
                return ProcessCommand("harvest_wood")

        # Check shelter material needs (simple_building_materials feeds ShelterDrive)
        building_materials = registry.get_commodity("simple_building_materials")
        if building_materials:
            bm_quantity = actor.inventory.get_quantity(building_materials)
            if bm_quantity < 3:
                # Bootstrap recipe: 2 wood + simple_tools -> 1 building material
                if actor.can_execute_process("make_building_materials_wood"):
                    return ProcessCommand("make_building_materials_wood")
                # Can't make yet (likely short on wood); gather more wood
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

    # Inventory levels to retain when selling surplus, for goods that are not
    # backed by a drive (drive goods derive their keep level from target_units).
    NON_DRIVE_KEEP_LEVELS = {
        "simple_tools": 2,  # tools for production
        "wood": 2,  # raw input for tools/building materials
        "common_metal": 2,  # alternate building-material input
    }

    def decide_market_actions(self, actor: "Actor") -> List[MarketCommand]:
        """Buy drive needs (with willingness-to-pay) and sell surplus production."""
        if not actor.planet:
            return []

        market = actor.planet.market
        commands: List[MarketCommand] = []

        # Cancel all existing orders before re-posting.
        existing_orders = market.get_actor_orders(actor)
        for order in existing_orders["buy"] + existing_orders["sell"]:
            commands.append(CancelOrderCommand(order.order_id))

        # Buy drive materials (food/clothing/shelter/health) at willingness-to-pay.
        commands.extend(self._drive_buy_commands(actor, market))

        # Acquire tools, which are an enabler for production rather than a drive.
        commands.extend(self._tool_buy_commands(actor, market))

        # Sell surplus inventory above what we want to keep.
        commands.extend(self._sell_excess_commands(actor, market))

        return commands

    def _tool_buy_commands(self, actor: Actor, market: "Market") -> List[MarketCommand]:
        """Buy simple_tools up to a buffer, bounded by willingness to pay."""
        tools = actor.sim.commodity_registry.get_commodity("simple_tools")
        if not tools:
            return []

        keep = self.NON_DRIVE_KEEP_LEVELS["simple_tools"]
        have = actor.inventory.get_quantity(tools)
        if have >= keep:
            return []
        need = keep - have

        willingness = self._calculate_tool_willingness_to_pay(actor)
        if willingness <= 0:
            return []

        market_sell_orders = sorted(
            [o for o in market.sell_orders.get(tools, []) if o.actor != actor],
            key=lambda o: (o.price, o.timestamp),
        )

        if market_sell_orders:
            ask = market_sell_orders[0].price
            if ask > willingness:
                return []  # Too expensive — make them instead (economic action).
            qty = min(need, actor.money // ask)
            if qty > 0:
                return [PlaceBuyOrderCommand(tools, qty, ask)]
            return []

        # No sellers: post a standing bid at willingness to pay to express demand.
        qty = min(need, actor.money // willingness)
        if qty > 0:
            return [PlaceBuyOrderCommand(tools, qty, willingness)]
        return []

    def _sell_excess_commands(
        self, actor: Actor, market: "Market"
    ) -> List[MarketCommand]:
        """Sell inventory above keep levels, as a price taker on standing bids."""
        commands: List[MarketCommand] = []
        for commodity in actor.sim.commodity_registry.all_commodities():
            if not commodity.transportable:
                continue
            keep = self._keep_level(actor, commodity)
            available = actor.inventory.get_available_quantity(commodity)
            if available <= keep:
                continue
            quantity_to_sell = available - keep

            market_buy_orders = sorted(
                [o for o in market.buy_orders.get(commodity, []) if o.actor != actor],
                key=lambda o: (-o.price, o.timestamp),
            )
            if market_buy_orders:
                best_buy_order = market_buy_orders[0]
                commands.append(
                    PlaceSellOrderCommand(
                        commodity, quantity_to_sell, best_buy_order.price
                    )
                )
        return commands

    def _keep_level(self, actor: Actor, commodity: "CommodityDefinition") -> int:
        """Inventory level to retain for a commodity before selling surplus."""
        for drive in actor.drives:
            if commodity in drive.materials():
                return drive.target_units()
        return self.NON_DRIVE_KEEP_LEVELS.get(commodity.id, 0)
