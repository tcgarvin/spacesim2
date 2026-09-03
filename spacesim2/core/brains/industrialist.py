import math
import random
from typing import TYPE_CHECKING, Dict, List, Optional

from spacesim2.core.actor_brain import (
    GOVERNMENT_WAGE,
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
    from spacesim2.core.actor import Actor
    from spacesim2.core.commodity import CommodityDefinition
    from spacesim2.core.market import Market
    from spacesim2.core.process import ProcessDefinition

# Notional value of a non-transportable facility when it is itself a recipe
# output. Production recipes value facilities via amortized build cost.
FACILITY_NOTIONAL_VALUE = 50.0
# Range of the per-actor facility amortization horizon. It encodes risk
# appetite: a higher horizon spreads the lump-sum build cost over more
# expected uses, so the actor is more willing to build on spec. Randomizing
# per actor also de-correlates choices, so the population does not stampede
# into one recipe during a cold start.
FACILITY_HORIZON_MIN = 150
FACILITY_HORIZON_MAX = 600
# Turns between checks that the chosen recipe is still profitable. Entry
# requires a 20% margin and exit waits for an outright loss; the band between
# is hysteresis so producers do not thrash on price noise.
EXIT_CHECK_INTERVAL = 10
# Premium over imputed cost when resting a procurement bid for a never-traded
# input. Must exceed the 1.2 entry margin: suppliers impute about the same
# cost we do, so a lower bid never triggers supplier entry and the cold-start
# standoff moves one tier up the chain.
PROCUREMENT_BOOTSTRAP_MARGIN = 1.25


class IndustrialistBrain(ActorBrain):
    """Decision-making logic for industrialist actors who specialize in production."""

    def __init__(self) -> None:
        self.chosen_recipe_id: Optional[str] = None
        self.turns_since_recipe_evaluation: int = 0
        self.facility_amortization_horizon: int = random.randint(
            FACILITY_HORIZON_MIN, FACILITY_HORIZON_MAX
        )

    def decide_economic_action(self, actor: "Actor") -> Optional[EconomicCommand]:
        """Decide which economic action to take this turn."""
        # Shared with decide_market_actions later this turn; see BrainCache.
        cache = self._turn_cache(actor)

        # 1% chance per turn to re-evaluate the recipe.
        self.turns_since_recipe_evaluation += 1
        if self._should_reevaluate_recipe():
            self.chosen_recipe_id = self._select_new_recipe(actor, cache)
            self.turns_since_recipe_evaluation = 0
        elif (
            self.chosen_recipe_id
            and actor.planet
            and self.turns_since_recipe_evaluation >= EXIT_CHECK_INTERVAL
        ):
            # Exit an unprofitable line: if the recipe no longer covers its
            # inputs plus a turn of labor, drop it and re-select, falling back
            # to government work when nothing is viable.
            process = actor.sim.process_registry.get_process(self.chosen_recipe_id)
            if process:
                score = self._calculate_recipe_score(
                    actor,
                    actor.planet.market,
                    process,
                    memo=cache.imputed_cost,
                    require_entry_margin=False,
                )
                if score <= 0:
                    self.chosen_recipe_id = None
            self.turns_since_recipe_evaluation = 0

        if not self.chosen_recipe_id:
            self.chosen_recipe_id = self._select_new_recipe(actor, cache)
            self.turns_since_recipe_evaluation = 0

        registry = actor.sim.commodity_registry

        # Critical needs first.
        food_commodity = registry.get_commodity("food")
        biomass_commodity = registry.get_commodity("biomass")
        clothing_commodity = registry.get_commodity("clothing")
        fiber_commodity = registry.get_commodity("fiber")

        if not food_commodity:
            return GovernmentWorkCommand()

        food_quantity = actor.inventory.get_quantity(food_commodity)
        if food_quantity < 2:
            if actor.can_execute_process("make_food"):
                return ProcessCommand("make_food")
            if biomass_commodity:
                biomass_quantity = actor.inventory.get_quantity(biomass_commodity)
                if biomass_quantity < 4 and actor.can_execute_process("gather_biomass"):
                    return ProcessCommand("gather_biomass")

        if clothing_commodity and fiber_commodity:
            clothing_quantity = actor.inventory.get_quantity(clothing_commodity)
            if clothing_quantity < 1:
                if actor.can_execute_process("make_clothing"):
                    return ProcessCommand("make_clothing")
                fiber_quantity = actor.inventory.get_quantity(fiber_commodity)
                if fiber_quantity < 4 and actor.can_execute_process("gather_fiber"):
                    return ProcessCommand("gather_fiber")

        # Build facilities and tools the chosen recipe needs.
        if self.chosen_recipe_id:
            process = actor.sim.process_registry.get_process(self.chosen_recipe_id)
            if process:
                for facility in process.facilities_required:
                    if not actor.inventory.has_quantity(facility, 1):
                        build_process_id = self._get_build_process_for_facility(
                            facility
                        )
                        if build_process_id and actor.can_execute_process(
                            build_process_id
                        ):
                            return ProcessCommand(build_process_id)

                for tool in process.tools_required:
                    if not actor.inventory.has_quantity(tool, 1):
                        if actor.can_execute_process("make_simple_tools"):
                            return ProcessCommand("make_simple_tools")

        if self.chosen_recipe_id and actor.can_execute_process(self.chosen_recipe_id):
            return ProcessCommand(self.chosen_recipe_id)

        return GovernmentWorkCommand()

    def decide_market_actions(self, actor: "Actor") -> List[MarketCommand]:
        """Buy personal needs and recipe inputs; sell recipe outputs."""
        if not actor.planet:
            return []

        market = actor.planet.market
        commands: List[MarketCommand] = []

        # Cancel all existing orders before re-posting.
        existing_orders = market.get_actor_orders(actor)
        for order in existing_orders["buy"] + existing_orders["sell"]:
            commands.append(CancelOrderCommand(order.order_id))

        # Shared with decide_economic_action earlier this turn: market quotes
        # carry over unconditionally, and replacement and imputed costs are
        # reused unless the economic command changed inventory or skills.
        # See BrainCache.
        cache = self._turn_cache(actor)

        # Personal consumption at willingness-to-pay. Industrialists rely on
        # the market for their own drives; this is the same drive-backed
        # demand colonists use.
        commands.extend(self._drive_buy_commands(actor, market, cache))

        # Recipe inputs and outputs.
        if self.chosen_recipe_id:
            recipe_commands = self._get_recipe_trading_commands(actor, market, cache)
            commands.extend(recipe_commands)

        return commands

    def _should_reevaluate_recipe(self) -> bool:
        """1% chance per turn to re-evaluate the recipe choice."""
        return random.random() < 0.01

    def _select_new_recipe(
        self, actor: "Actor", cache: Optional[BrainCache] = None
    ) -> Optional[str]:
        """Select a recipe, weighted by expected profit.

        Weighting toward more profitable recipes makes industrialists
        specialize in what their planet is good at.
        """
        if not actor.planet:
            return None

        market = actor.planet.market
        recipe_scores: list[tuple[str, float]] = []

        # One memo for the whole pass and, via BrainCache, the rest of this
        # actor-turn. Imputed unit costs depend only on fixed market state
        # and this actor's facility ownership and horizon.
        memo: Dict[str, float] = cache.imputed_cost if cache is not None else {}
        for process in actor.sim.process_registry.all_processes():
            score = self._calculate_recipe_score(actor, market, process, memo)
            if score > 0:
                recipe_scores.append((process.id, score))

        if not recipe_scores:
            return None

        # Weighted random selection by score.
        total_score = sum(score for _, score in recipe_scores)
        if total_score <= 0:
            return None

        roll = random.random() * total_score
        cumulative = 0.0
        for process_id, score in recipe_scores:
            cumulative += score
            if roll <= cumulative:
                return process_id

        # Not reachable in practice.
        return recipe_scores[-1][0]

    def _calculate_recipe_score(
        self,
        actor: "Actor",
        market: "Market",
        process: "ProcessDefinition",
        memo: Optional[Dict[str, float]] = None,
        require_entry_margin: bool = True,
    ) -> float:
        """Profitability score for a recipe.

        Expected profit: output value minus inputs and a turn of labor. With
        ``require_entry_margin``, the default when picking a recipe,
        anything below a 20% margin scores 0. Exit decisions pass False and
        act on raw profit, so the margin band is hysteresis. ``memo`` caches
        imputed unit costs across one recipe-selection pass, where market
        state is fixed.
        """
        if memo is None:
            memo = {}

        # Inputs, tools, and facilities are valued by make-or-buy imputation,
        # so a recipe is not dismissed because a deep intermediate has never
        # traded.
        total_input_cost = self._impute_recipe_cost(
            actor, market, process, 0, frozenset(), memo
        )
        if math.isinf(total_input_cost):
            return 0.0

        attribute_modifier = 1.0
        if process.resource_attribute and actor.planet:
            attr_value = actor.planet.attributes.get_availability(
                process.resource_attribute.commodity
            )
            attribute_modifier = attr_value

        # Outputs are not imputed. Value is realized only if a real buyer
        # bids, and the market maker bids on every transportable good, so an
        # unsellable output is worthless to this actor.
        total_output_value = 0.0
        for commodity, quantity in process.outputs.items():
            # Non-transportable outputs are facilities for personal use; give
            # them a notional value for enabling other recipes.
            if not commodity.transportable:
                total_output_value += FACILITY_NOTIONAL_VALUE * quantity
                continue

            bid, _ = market.get_bid_ask_spread(commodity)
            if bid is not None:
                price = bid
            else:
                price = market.get_avg_price(commodity)
                if price <= 0:
                    return 0.0
            expected_quantity = quantity * attribute_modifier
            total_output_value += price * expected_quantity

        # Entry requires a 20% margin over costs, which include labor. Exit
        # checks skip the margin.
        if require_entry_margin and total_output_value < total_input_cost * 1.2:
            return 0.0

        return total_output_value - total_input_cost

    def _calculate_tool_willingness_to_pay(
        self, actor: "Actor", market: "Market", cache: Optional[BrainCache] = None
    ) -> int:
        """Maximum price an industrialist pays for a tool.

        Input cost to make the tool, 2 common_metal, plus the opportunity
        cost of the turn: recipe profit or the government wage.
        """
        common_metal = actor.sim.commodity_registry.get_commodity("common_metal")
        if not common_metal:
            return GOVERNMENT_WAGE * 10

        bid, ask = _get_bid_ask(market, common_metal, cache)
        metal_price = (
            ask if ask is not None else _get_avg_price(market, common_metal, cache)
        )
        input_cost = int(metal_price * 2)

        opportunity_cost = GOVERNMENT_WAGE
        if self.chosen_recipe_id:
            process = actor.sim.process_registry.get_process(self.chosen_recipe_id)
            if process:
                score = self._calculate_recipe_score(
                    actor,
                    market,
                    process,
                    memo=cache.imputed_cost if cache is not None else None,
                )
                if score > GOVERNMENT_WAGE:
                    opportunity_cost = int(score)

        return input_cost + opportunity_cost

    def _buy_command(
        self,
        actor: "Actor",
        market: "Market",
        commodity: "CommodityDefinition",
        quantity_to_buy: int,
        cache: Optional[BrainCache] = None,
    ) -> List[MarketCommand]:
        """Acquire ``quantity_to_buy`` units of ``commodity``.

        Lifts the cheapest resting ask, or, if none exists, rests a bid at
        the reference price so a seller can find us. Resting a bid without a
        pre-existing ask breaks the producer/consumer standoff on
        never-traded intermediates: a medicine maker must signal demand for
        refined_chemicals before any refiner will produce them.
        """
        if quantity_to_buy <= 0:
            return []
        asks = sorted(
            [
                o
                for o in market.sell_orders.get(commodity, [])
                if o.actor != actor and not o.cancelled
            ],
            key=lambda o: (o.price, o.timestamp),
        )
        if asks:
            price = asks[0].price
        elif market.has_price_signal(commodity):
            # A real trade price exists, possibly stale. Anchor to it.
            price = market.get_avg_price(commodity)
        else:
            # Never-traded good: get_avg_price would return its fabricated
            # default of 10, which sits below a rational seller's
            # replacement-cost floor and deadlocks price discovery. Bid our
            # own imputed replacement cost, rounded up so we clear that floor
            # rather than fall a credit short. Fall back to the avg default
            # only when the good cannot be imputed at all.
            #
            # PROCUREMENT_BOOTSTRAP_MARGIN matters: a supplier enters a recipe
            # only when the best bid covers 1.2x their imputed cost, and buyer
            # and supplier impute nearly the same cost, so a bid at 1.0x cost
            # sits permanently below every supplier's entry threshold. Paying
            # a small premium to bootstrap a local supplier beats producing
            # nothing.
            memo = cache.imputed_cost if cache is not None else {}
            imputed = self._imputed_unit_cost(
                actor, market, commodity, 0, frozenset(), memo
            )
            if math.isinf(imputed):
                price = market.get_avg_price(commodity)
            else:
                price = math.ceil(imputed * PROCUREMENT_BOOTSTRAP_MARGIN)
        if price <= 0:
            return []
        affordable = min(quantity_to_buy, actor.money // price)
        if affordable <= 0:
            return []
        return [PlaceBuyOrderCommand(commodity, affordable, price)]

    def _sell_command(
        self,
        actor: "Actor",
        market: "Market",
        commodity: "CommodityDefinition",
        cache: Optional[BrainCache] = None,
    ) -> List[MarketCommand]:
        """Sell all available units of ``commodity``, floored at replacement cost.

        Skips non-transportable goods; facilities are not tradable.
        """
        if not commodity.transportable:
            return []
        available = actor.inventory.get_available_quantity(commodity)
        return self._sell_at_or_above_cost(actor, market, commodity, available, cache)

    def _get_recipe_trading_commands(
        self, actor: "Actor", market: "Market", cache: Optional[BrainCache] = None
    ) -> List[MarketCommand]:
        """Generate trading commands for recipe inputs and outputs."""
        commands: List[MarketCommand] = []

        if self.chosen_recipe_id is None:
            return commands

        process = actor.sim.process_registry.get_process(self.chosen_recipe_id)
        if not process:
            return commands

        tool_willingness_to_pay = self._calculate_tool_willingness_to_pay(
            actor, market, cache
        )

        # Keep a buffer of 2 of each required tool.
        TOOL_BUFFER = 2
        for tool in process.tools_required:
            current_quantity = actor.inventory.get_quantity(tool)
            if current_quantity < TOOL_BUFFER:
                quantity_to_buy = TOOL_BUFFER - current_quantity

                market_sell_orders = sorted(
                    [
                        o
                        for o in market.sell_orders.get(tool, [])
                        if o.actor != actor and not o.cancelled
                    ],
                    key=lambda o: (o.price, o.timestamp),
                )

                if market_sell_orders:
                    best_sell_order = market_sell_orders[0]
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
                    # No sellers: rest a bid at willingness to pay.
                    max_affordable = min(
                        quantity_to_buy, actor.money // tool_willingness_to_pay
                    )

                    if max_affordable > 0:
                        commands.append(
                            PlaceBuyOrderCommand(
                                tool, max_affordable, tool_willingness_to_pay
                            )
                        )

        for commodity, needed_quantity in process.inputs.items():
            current_quantity = actor.inventory.get_quantity(commodity)
            commands.extend(
                self._buy_command(
                    actor, market, commodity, needed_quantity - current_quantity, cache
                )
            )

        # Buy materials to build any facility this recipe needs but we lack.
        # Otherwise an actor picks a facility-gated recipe and tries to build
        # the facility but never procures the bricks or glass, and the
        # facility tier cannot cold-start.
        for facility in process.facilities_required:
            if actor.inventory.has_quantity(facility, 1):
                continue
            build_process_id = self._get_build_process_for_facility(facility)
            if not build_process_id:
                continue
            build_process = actor.sim.process_registry.get_process(build_process_id)
            if not build_process:
                continue
            # The build needs commodity inputs and tools. Require one of each
            # missing tool too, or can_execute_process(build) never becomes
            # true.
            build_requirements: Dict["CommodityDefinition", int] = dict(
                build_process.inputs
            )
            for tool in build_process.tools_required:
                build_requirements.setdefault(tool, 1)
            for commodity, needed_quantity in build_requirements.items():
                current_quantity = actor.inventory.get_quantity(commodity)
                commands.extend(
                    self._buy_command(
                        actor,
                        market,
                        commodity,
                        needed_quantity - current_quantity,
                        cache,
                    )
                )

        for commodity, _ in process.outputs.items():
            commands.extend(self._sell_command(actor, market, commodity, cache))

        return commands
