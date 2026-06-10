import math
import random
from typing import TYPE_CHECKING, Dict, List, Optional

from spacesim2.core.actor_brain import (
    GOVERNMENT_WAGE,
    TOOL_EXPECTED_LIFESPAN,
    ActorBrain,
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

# Notional value of a (non-transportable) facility when it is itself a recipe
# output. Production recipes value facilities via amortized build cost instead.
FACILITY_NOTIONAL_VALUE = 50.0
# Bound on how deep make-or-buy imputation recurses through production chains.
MAX_IMPUTE_DEPTH = 6
# Per-actor facility amortization horizon is drawn from this range. It encodes
# risk appetite: a higher horizon spreads the lump-sum build cost over more
# expected uses (cheaper per unit -> more willing to build on spec); a lower
# horizon is conservative. Randomizing per actor also de-correlates choices so
# the population doesn't stampede into the same recipe during a cold start.
FACILITY_HORIZON_MIN = 150
FACILITY_HORIZON_MAX = 600
# How often to check whether the chosen recipe is still profitable. Entry
# requires a 20% margin while exit waits for an outright loss; the band
# between the two is hysteresis so producers don't thrash on price noise.
EXIT_CHECK_INTERVAL = 10


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
        # First check if we need to re-evaluate our recipe (1% chance per turn)
        self.turns_since_recipe_evaluation += 1
        if self._should_reevaluate_recipe():
            self.chosen_recipe_id = self._select_new_recipe(actor)
            self.turns_since_recipe_evaluation = 0
        elif (
            self.chosen_recipe_id
            and actor.planet
            and self.turns_since_recipe_evaluation >= EXIT_CHECK_INTERVAL
        ):
            # Exit an unprofitable line of business: if the recipe no longer
            # covers its inputs plus a turn of labor, drop it and re-select
            # (falling back to government work when nothing is viable).
            process = actor.sim.process_registry.get_process(self.chosen_recipe_id)
            if process:
                score = self._calculate_recipe_score(
                    actor, actor.planet.market, process, require_entry_margin=False
                )
                if score <= 0:
                    self.chosen_recipe_id = None
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

        # 1. Buy commodities for personal consumption at willingness-to-pay.
        #    Industrialists specialize in production and rely on the market for
        #    their own drives (food/clothing/shelter/health); this is the same
        #    generic, drive-backed demand the colonists use.
        commands.extend(self._drive_buy_commands(actor, market))

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

        # One memo shared across the whole pass: imputed unit costs depend only
        # on (fixed) market state and this actor's facility ownership/horizon.
        memo: Dict[str, float] = {}
        for process in actor.sim.process_registry.all_processes():
            score = self._calculate_recipe_score(actor, market, process, memo)
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

    def _imputed_unit_cost(
        self,
        actor: "Actor",
        market: "Market",
        commodity: "CommodityDefinition",
        depth: int,
        visiting: frozenset[str],
        memo: Dict[str, float],
    ) -> float:
        """Best estimate of the per-unit cost to acquire ``commodity``: buy it,
        or, if the market can't price it, make it.

        This is the keystone that lets the planner "see through" intermediates
        that have never traded (e.g. glass, refined_chemicals): instead of
        bailing out, we recursively impute their cost from the cheapest recipe
        that produces them. Returns ``math.inf`` when the commodity can be
        neither bought nor produced (no recipe, a production cycle, or the
        recursion depth bound is hit), which callers treat as "not viable".
        """
        # 1. Buy it: a live ask is the truest cost; fall back to last-traded avg.
        _, ask = market.get_bid_ask_spread(commodity)
        if ask is not None:
            return float(ask)
        avg = market.get_avg_price(commodity)
        if avg > 0:
            return float(avg)

        if commodity.id in memo:
            return memo[commodity.id]
        if depth >= MAX_IMPUTE_DEPTH or commodity.id in visiting:
            return math.inf  # depth bound or production cycle -> can't value

        # 2. Make it: cheapest producing recipe, costed recursively.
        visiting = visiting | {commodity.id}
        best = math.inf
        for process in actor.sim.process_registry.all_processes():
            out_qty = 0
            for out_commodity, qty in process.outputs.items():
                if out_commodity.id == commodity.id:
                    out_qty = qty
                    break
            if out_qty <= 0:
                continue
            recipe_cost = self._impute_recipe_cost(
                actor, market, process, depth, visiting, memo
            )
            if math.isinf(recipe_cost):
                continue
            best = min(best, recipe_cost / out_qty)

        if not math.isinf(best):
            memo[commodity.id] = best
        return best

    def _impute_recipe_cost(
        self,
        actor: "Actor",
        market: "Market",
        process: "ProcessDefinition",
        depth: int,
        visiting: frozenset[str],
        memo: Dict[str, float],
    ) -> float:
        """Total imputed cost to execute ``process`` once: a turn of labor at
        the government wage, recursively-valued inputs, plus amortized tool
        and facility costs. ``math.inf`` if any component can't be valued.
        """
        total = float(GOVERNMENT_WAGE)

        for commodity, quantity in process.inputs.items():
            unit = self._imputed_unit_cost(
                actor, market, commodity, depth + 1, visiting, memo
            )
            if math.isinf(unit):
                return math.inf
            total += unit * quantity

        # Tools the actor lacks must be acquired; amortize over their lifespan.
        for tool in process.tools_required:
            if actor.inventory.has_quantity(tool, 1):
                continue
            unit = self._imputed_unit_cost(
                actor, market, tool, depth + 1, visiting, memo
            )
            if math.isinf(unit):
                return math.inf
            total += unit / TOOL_EXPECTED_LIFESPAN

        # Facilities the actor lacks are a lump-sum build cost amortized over
        # this actor's (risk-appetite-dependent) expected usage horizon.
        for facility in process.facilities_required:
            if actor.inventory.has_quantity(facility, 1):
                continue
            build_process_id = self._get_build_process_for_facility(facility)
            if not build_process_id:
                return math.inf
            build_process = actor.sim.process_registry.get_process(build_process_id)
            if not build_process:
                return math.inf
            build_cost = self._impute_recipe_cost(
                actor, market, build_process, depth + 1, visiting, memo
            )
            if math.isinf(build_cost):
                return math.inf
            total += build_cost / self.facility_amortization_horizon

        return total

    def _calculate_recipe_score(
        self,
        actor: "Actor",
        market: "Market",
        process: "ProcessDefinition",
        memo: Optional[Dict[str, float]] = None,
        require_entry_margin: bool = True,
    ) -> float:
        """Calculate a profitability score for a recipe.

        Returns expected profit (output value minus inputs and a turn of
        labor). With ``require_entry_margin`` (the default, used when picking
        a recipe) anything below a 20% margin scores 0; exit decisions pass
        False and act on the raw profit, so the margin band acts as
        hysteresis. ``memo`` caches imputed unit costs across a single
        recipe-selection pass (market state is fixed there).
        """
        if memo is None:
            memo = {}

        # Inputs (and the tools/facilities a recipe needs) are valued via
        # make-or-buy imputation, so a recipe is not dismissed merely because a
        # deep intermediate has never traded.
        total_input_cost = self._impute_recipe_cost(
            actor, market, process, 0, frozenset(), memo
        )
        if math.isinf(total_input_cost):
            return 0.0

        # Determine planet attribute modifier
        attribute_modifier = 1.0
        if process.resource_attribute and actor.planet and actor.planet.attributes:
            attr_value = actor.planet.attributes.get_availability(
                process.resource_attribute.commodity
            )
            attribute_modifier = attr_value

        # Calculate expected output value. Unlike inputs, outputs are NOT
        # imputed: value can only be realized if a real buyer bids (the market
        # maker bids on every transportable good), so an unsellable output is
        # genuinely worthless to this actor.
        total_output_value = 0.0
        for commodity, quantity in process.outputs.items():
            # Non-transportable outputs (facilities) are for personal use, not
            # sale; give them a notional value for enabling other recipes.
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

        # Entry requires a 20% margin over costs (which include labor); exit
        # checks skip the margin and act on raw profit.
        if require_entry_margin and total_output_value < total_input_cost * 1.2:
            return 0.0

        # Score is expected profit (output - inputs - labor)
        return total_output_value - total_input_cost

    def _calculate_tool_willingness_to_pay(
        self, actor: "Actor", market: "Market"
    ) -> int:
        """Calculate max price industrialist would pay for a tool.

        For industrialists, willingness to pay is based on:
        - Input cost to make the tool (2 common_metal)
        - Opportunity cost of the turn (recipe profit or govt wage)
        """
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

    def _buy_command(
        self,
        actor: "Actor",
        market: "Market",
        commodity: "CommodityDefinition",
        quantity_to_buy: int,
    ) -> List[MarketCommand]:
        """Acquire ``quantity_to_buy`` units of ``commodity``: lift the cheapest
        resting ask, or, if none exists, rest a bid at the reference price so a
        seller can find us.

        Resting a bid without a pre-existing ask is what breaks the
        producer/consumer standoff on never-traded intermediates: a medicine
        maker must signal demand for refined_chemicals before any refiner will
        produce them.
        """
        if quantity_to_buy <= 0:
            return []
        asks = sorted(
            [o for o in market.sell_orders.get(commodity, []) if o.actor != actor],
            key=lambda o: (o.price, o.timestamp),
        )
        price = asks[0].price if asks else market.get_avg_price(commodity)
        if price <= 0:
            return []
        affordable = min(quantity_to_buy, actor.money // price)
        if affordable <= 0:
            return []
        return [PlaceBuyOrderCommand(commodity, affordable, price)]

    def _sell_command(
        self, actor: "Actor", market: "Market", commodity: "CommodityDefinition"
    ) -> List[MarketCommand]:
        """Sell all available units of ``commodity``, floored at replacement
        cost. Skips non-transportable goods (facilities aren't tradable).
        """
        if not commodity.transportable:
            return []
        available = actor.inventory.get_available_quantity(commodity)
        return self._sell_at_or_above_cost(actor, market, commodity, available)

    def _get_recipe_trading_commands(
        self, actor: "Actor", market: "Market"
    ) -> List[MarketCommand]:
        """Generate trading commands for recipe inputs and outputs."""
        commands: List[MarketCommand] = []

        if self.chosen_recipe_id is None:
            return commands

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
            commands.extend(
                self._buy_command(
                    actor, market, commodity, needed_quantity - current_quantity
                )
            )

        # Buy materials to build any facility this recipe needs but we lack.
        # Without this, an actor will choose a facility-gated recipe and try to
        # build the facility, but never procure the bricks/glass to do so -
        # the connective tissue that lets the facility tier cold-start.
        for facility in process.facilities_required:
            if actor.inventory.has_quantity(facility, 1):
                continue
            build_process_id = self._get_build_process_for_facility(facility)
            if not build_process_id:
                continue
            build_process = actor.sim.process_registry.get_process(build_process_id)
            if not build_process:
                continue
            # The build needs both commodity inputs (bricks, glass, ...) and
            # tools (e.g. simple_tools). Require one of each missing tool too,
            # or can_execute_process(build) never becomes true.
            build_requirements: Dict["CommodityDefinition", int] = dict(
                build_process.inputs
            )
            for tool in build_process.tools_required:
                build_requirements.setdefault(tool, 1)
            for commodity, needed_quantity in build_requirements.items():
                current_quantity = actor.inventory.get_quantity(commodity)
                commands.extend(
                    self._buy_command(
                        actor, market, commodity, needed_quantity - current_quantity
                    )
                )

        # Sell outputs from recipe
        for commodity, _ in process.outputs.items():
            commands.extend(self._sell_command(actor, market, commodity))

        return commands
