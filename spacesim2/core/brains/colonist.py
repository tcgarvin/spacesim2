from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from spacesim2.core.actor import Actor
from spacesim2.core.actor_brain import (
    ActorBrain,
    BrainCache,
    _get_avg_price,
    _get_bid_ask,
)
from spacesim2.core.commands import (
    CancelOrderCommand,
    EconomicCommand,
    GovernmentWorkCommand,
    MarketCommand,
    PlaceBuyOrderCommand,
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
        # Per-actor-turn memoization: market quotes and process cost/yield
        # figures are shared with decide_market_actions later this turn (the
        # market can't move in between), while inventory/skill-dependent
        # entries auto-invalidate if the economic command changes actor
        # state. See BrainCache for the invalidation rule.
        cache = self._turn_cache(actor)

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
                    willingness_to_pay = self._calculate_tool_willingness_to_pay(
                        actor, cache
                    )
                    bid, ask = _get_bid_ask(market, tools_commodity, cache)

                    # If tools are available at a price at or below our willingness to pay,
                    # skip making - we'll buy in the market phase instead
                    if ask is not None and ask <= willingness_to_pay:
                        should_make_tools = False

                if should_make_tools and actor.can_execute_process("make_simple_tools"):
                    return ProcessCommand("make_simple_tools")

        # Try to find the most profitable process
        market = actor.planet.market if actor.planet else None
        if market:
            best_process = self._find_most_profitable_process(actor, market, cache)

            # best_process is only ever set inside the scan when
            # can_execute_process was already true for it, and nothing
            # mutates actor state between that scan and here (this whole
            # method runs before the returned command is executed) - so
            # re-checking can_execute_process would just repeat work.
            if best_process:
                return ProcessCommand(best_process.id)

        # If no processes can be executed, do government work
        return GovernmentWorkCommand()

    def _find_most_profitable_process(
        self, actor: Actor, market: "Market", cache: Optional[BrainCache] = None
    ) -> Optional["ProcessDefinition"]:
        """Find the most profitable process based on *expected* outcomes.

        Output value is discounted by planet resource availability and the
        actor's skill (failed runs waste the turn). Without that discount, a
        high ore price lures colonists on resource-poor planets into mining
        loops that fail nearly every turn while they starve.
        """
        best_process, _raw_profit = self._best_process_and_raw_profit(
            actor, market, cache
        )
        return best_process

    def _best_process_and_raw_profit(
        self, actor: Actor, market: "Market", cache: Optional[BrainCache] = None
    ) -> Tuple[Optional["ProcessDefinition"], float]:
        """Scan the process registry once, returning both the actor's best
        process (selected on *discounted* expected profit, same criterion as
        ``_find_most_profitable_process``) and that process's *raw*
        (undiscounted output_value - input_cost) profit, which is what
        ``_calculate_turn_opportunity_cost`` reports as the opportunity cost
        of a turn.

        Three-level memoization (see BrainCache), matching what actually
        changes when the mid-turn economic command executes:

        * ``cache.best_result`` — the final answer; dropped on any
          inventory/skills change (it read ``can_execute``).
        * ``cache.ranked_profits`` — every process's profit figures sorted by
          descending discounted profit; survives inventory-only changes.
        * ``cache.process_quote_values`` — the quote-derived part (input
          cost / output value per process), which depends on neither skills
          nor inventory; survives everything within the turn. A successful
          ProcessCommand bumps skills every time, so this is the level that
          spares the second ``decide_*`` call a fresh quote scan: re-ranking
          from it is a cheap skill-multiply and sort.
        """
        if cache is not None and cache.best_result is not None:
            return cache.best_result

        ranked = cache.ranked_profits if cache is not None else None
        if ranked is None:
            quote_values = cache.process_quote_values if cache is not None else None
            if quote_values is None:
                quote_values = []
                for process in actor.sim.process_registry.all_processes():
                    # Calculate potential profit using actual market bid/ask
                    # prices
                    input_cost = 0.0
                    for commodity, quantity in process.inputs.items():
                        # Use ask price (what we'd pay to buy) if available
                        _bid, ask = _get_bid_ask(market, commodity, cache)
                        price = (
                            ask
                            if ask is not None
                            else _get_avg_price(market, commodity, cache)
                        )
                        input_cost += price * quantity

                    output_value = 0.0
                    for commodity, quantity in process.outputs.items():
                        # Use bid price (what buyers will pay) if available
                        bid, _ask = _get_bid_ask(market, commodity, cache)
                        price = (
                            bid
                            if bid is not None
                            else _get_avg_price(market, commodity, cache)
                        )
                        output_value += price * quantity

                    quote_values.append((input_cost, output_value, process))
                if cache is not None:
                    cache.process_quote_values = quote_values

            ranked = [
                (
                    output_value
                    * self._expected_yield_modifier(actor, process, cache)
                    * self._expected_skill_factor(actor, process, cache)
                    - input_cost,
                    output_value - input_cost,
                    process,
                )
                for input_cost, output_value, process in quote_values
            ]
            # Stable sort: equal discounted profits keep registry order, so
            # the walk below picks the same winner the old
            # first-strictly-better registry scan did.
            ranked.sort(key=lambda entry: -entry[0])
            if cache is not None:
                cache.ranked_profits = ranked

        best_process: Optional["ProcessDefinition"] = None
        best_raw_profit = 0.0
        for discounted_profit, raw_profit, process in ranked:
            # Must exceed government work profit (same strict bar as the old
            # scan's best_discounted_profit = 10.0 starting value). Entries
            # are sorted, so once below the bar nothing later qualifies.
            if discounted_profit <= 10.0:
                break
            if actor.can_execute(process):
                best_process = process
                best_raw_profit = raw_profit
                break

        result = (best_process, best_raw_profit)
        if cache is not None:
            cache.best_result = result
        return result

    def _calculate_turn_opportunity_cost(
        self, actor: Actor, cache: Optional[BrainCache] = None
    ) -> int:
        """Calculate the opportunity cost of spending a turn making tools.

        This is the profit from the actor's next-best economic action.
        Returns GOVERNMENT_WAGE (10) as a minimum floor.
        """
        GOVERNMENT_WAGE = 10

        market = actor.planet.market if actor.planet else None
        if not market:
            return GOVERNMENT_WAGE

        best_process, raw_profit = self._best_process_and_raw_profit(
            actor, market, cache
        )
        if not best_process:
            return GOVERNMENT_WAGE

        return max(GOVERNMENT_WAGE, int(raw_profit))

    def _calculate_tool_willingness_to_pay(
        self, actor: Actor, cache: Optional[BrainCache] = None
    ) -> int:
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

        bid, ask = _get_bid_ask(market, common_metal, cache)
        metal_price = (
            ask if ask is not None else _get_avg_price(market, common_metal, cache)
        )
        input_cost = int(metal_price * 2)  # make_simple_tools requires 2 common_metal

        # Opportunity cost of spending a turn making tools
        opportunity_cost = self._calculate_turn_opportunity_cost(actor, cache)

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

        # Per-actor-turn memoization, shared with decide_economic_action
        # earlier this turn: market quotes carry over unconditionally (the
        # economic command can't move the order books), while replacement
        # costs and the profitability scan are reused only if the economic
        # command left inventory/skills untouched. See BrainCache.
        cache = self._turn_cache(actor)

        # Buy drive materials (food/clothing/shelter/health) at willingness-to-pay.
        commands.extend(self._drive_buy_commands(actor, market, cache))

        # Acquire tools, which are an enabler for production rather than a drive.
        commands.extend(self._tool_buy_commands(actor, market, cache))

        # Sell surplus inventory above what we want to keep.
        commands.extend(self._sell_excess_commands(actor, market, cache))

        return commands

    def _tool_buy_commands(
        self, actor: Actor, market: "Market", cache: Optional[BrainCache] = None
    ) -> List[MarketCommand]:
        """Buy simple_tools up to a buffer, bounded by willingness to pay."""
        tools = actor.sim.commodity_registry.get_commodity("simple_tools")
        if not tools:
            return []

        keep = self.NON_DRIVE_KEEP_LEVELS["simple_tools"]
        have = actor.inventory.get_quantity(tools)
        if have >= keep:
            return []
        need = keep - have

        willingness = self._calculate_tool_willingness_to_pay(actor, cache)
        if willingness <= 0:
            return []

        market_sell_orders = sorted(
            [
                o
                for o in market.sell_orders.get(tools, [])
                if o.actor != actor and not o.cancelled
            ],
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
        self, actor: Actor, market: "Market", cache: Optional[BrainCache] = None
    ) -> List[MarketCommand]:
        """Sell inventory above keep levels, floored at replacement cost."""
        commands: List[MarketCommand] = []
        keep_levels = self._keep_levels_by_commodity(actor)
        for commodity in actor.sim.commodity_registry.all_commodities():
            if not commodity.transportable:
                continue
            keep = keep_levels.get(commodity.id, 0)
            available = actor.inventory.get_available_quantity(commodity)
            if available <= keep:
                continue
            commands.extend(
                self._sell_at_or_above_cost(
                    actor, market, commodity, available - keep, cache
                )
            )
        return commands

    def _keep_level(self, actor: Actor, commodity: "CommodityDefinition") -> int:
        """Inventory level to retain for a commodity before selling surplus."""
        for drive in actor.drives:
            if commodity in drive.materials():
                return drive.target_units()
        return self.NON_DRIVE_KEEP_LEVELS.get(commodity.id, 0)

    def _keep_levels_by_commodity(self, actor: Actor) -> Dict[str, int]:
        """Precompute ``_keep_level`` for every commodity in one pass.

        Equivalent to calling ``_keep_level`` per commodity (same first-drive-
        wins precedence, same non-drive fallback), but replaces an O(commodities
        x drives) linear membership scan with a single O(drives) pass over
        ``actor.drives`` up front: there are ~40 commodities and only a
        handful of drives/materials, so inverting the lookup is strictly
        cheaper. Drive materials/target_units are fixed per drive instance
        for the whole turn (they don't depend on this-turn metrics), so this
        is safe to compute once per ``_sell_excess_commands`` call.
        """
        levels: Dict[str, int] = {}
        for drive in actor.drives:
            target = drive.target_units()
            for material in drive.materials():
                levels.setdefault(material.id, target)
        for commodity_id, keep in self.NON_DRIVE_KEEP_LEVELS.items():
            levels.setdefault(commodity_id, keep)
        return levels
