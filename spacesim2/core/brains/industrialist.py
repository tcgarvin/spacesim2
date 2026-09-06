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
# Margin a recipe must clear over its imputed cost before an actor will enter
# it. Exit waits for an outright loss; the band between is hysteresis so
# producers do not thrash on price noise.
ENTRY_MARGIN = 1.2
# Turns between checks that the chosen recipe is still profitable.
EXIT_CHECK_INTERVAL = 10
# Procurement bids for recipe inputs have two layers, mirroring the
# consumer-side design in ActorBrain._drive_buy_commands:
#
# 1. A ceiling, the netback value of the input. It is what one unit can be
#    worth to this actor given what the recipe's output sells for: the run's
#    output value, less every other cost of the run, divided by the units
#    consumed and by ENTRY_MARGIN so the recipe still clears its entry
#    threshold after paying the ceiling. This is what carries a demand signal
#    down a tier: a medicine maker bidding 140 for medicine can pay far more
#    for refined_chemicals than the chemicals' own stale average says.
# 2. A posted bid that starts at a reference price and escalates toward the
#    ceiling as the market's scarcity pressure grows, so a bid only rises
#    where demand is actually going unfilled.
#
# The ceiling needs both an output value and an imputed recipe cost. When
# either is unavailable the bid falls back to the older single-layer pricing
# below, so the netback layer is strictly additive.
#
# Premium over imputed cost when resting a procurement bid for a never-traded
# input. Must exceed ENTRY_MARGIN: suppliers impute about the same cost we do,
# so a lower bid never triggers supplier entry and the cold-start standoff
# moves one tier up the chain.
PROCUREMENT_BOOTSTRAP_MARGIN = 1.25
# Gate for paying that premium on a good that HAS traded before. It applies
# only on the fallback path; where a netback ceiling exists, scarcity pressure
# escalates the bid continuously instead. Once a good has any trade history
# the bid would otherwise rest at the stale average, which can sit below every
# potential supplier's entry threshold, so the tier
# stays dead even though the average says a price exists. The premium is
# applied again only where the market itself says the good is unobtainable:
# no resting ask, chronic unmet demand, and essentially no recent turnover.
# Applying it unconditionally also unblocks the chain but bids up goods that
# have real supply, so it is inflationary; these gates confine it to a
# genuinely stalled market.
PROCUREMENT_STALL_PRESSURE = 1.0
PROCUREMENT_STALL_VOLUME = 0.5
# A chosen recipe that cannot execute for this many consecutive turns, with no
# change in the inventory of anything it needs, is unreachable rather than
# merely slow: the actor is doing government work every turn while holding a
# line it can never run. Procuring inputs or building a facility both move
# inventory, so neither is mistaken for being stuck.
RECIPE_STUCK_TURNS = 20
# Turns a recipe abandoned that way is excluded from re-selection, so the
# actor does not immediately re-pick it from the same ranking.
RECIPE_COOLDOWN_TURNS = 50
# Runs of output a recipe must be able to sell into the resting book before
# its top-of-book bid is believed. Market makers seed illiquid goods with
# one-unit probes an order of magnitude above fair value; at a horizon of one
# unit those probes read as demand and pull producers into goods nobody buys.
# Valuing output at the level that absorbs several runs ignores a probe
# without ignoring genuine thin demand, which shows up as depth.
OUTPUT_SALES_HORIZON_RUNS = 3
# Floor on that horizon, so a recipe yielding a fraction of a unit per run
# still has to clear more depth than a single probe.
MIN_OUTPUT_DEPTH_UNITS = 3
# Cap on what a never-traded output is worth, as a multiple of its imputed
# make cost. It must exceed PROCUREMENT_BOOTSTRAP_MARGIN, or the bid a buyer
# rests to bootstrap a cold-start intermediate would be capped below itself
# and no supplier would ever enter.
NEVER_TRADED_VALUE_CAP = 1.5
# Cap on the netback ceiling for a facility build material, as a multiple of
# its imputed unit cost. A build's ceiling divides the recipe's whole margin
# by the material's draw per run, which is the build quantity over a horizon
# of 150-600 runs, so the raw figure is in the hundreds per brick. Bids that
# high are entry-consistent but they let scarcity pressure run to its full
# range on goods with inelastic supply, and simple_building_materials is also
# the shelter material, so colonists were outbid for housing. Two matches the
# most a consumer drive pays over replacement cost at full deprivation. The
# multiple applies to the material's recipe cost, not its market average: a
# cap on the average rose with every fill the bid caused.
BUILD_INPUT_CEILING_CAP = 2.0
# Working buffer the liquidation sweep retains for goods not backed by a
# drive. Mirrors ColonistBrain.NON_DRIVE_KEEP_LEVELS: an industrialist also
# falls back on make_clothing and make_simple_tools for its own needs, which
# consume these. Drive goods derive their keep level from target_units.
NON_DRIVE_KEEP_LEVELS = {
    "simple_tools": 2,
    "wood": 2,
    "common_metal": 2,
}


class IndustrialistBrain(ActorBrain):
    """Decision-making logic for industrialist actors who specialize in production."""

    def __init__(self) -> None:
        self.chosen_recipe_id: Optional[str] = None
        self.turns_since_recipe_evaluation: int = 0
        self.facility_amortization_horizon: int = random.randint(
            FACILITY_HORIZON_MIN, FACILITY_HORIZON_MAX
        )
        # Consecutive turns the chosen recipe could not run with no change in
        # what it needs. See _update_stuck_tracking.
        self.stuck_turns: int = 0
        self.stuck_signature: Optional[tuple[tuple[str, int], ...]] = None
        # process id -> turn the recipe becomes selectable again.
        self.recipe_cooldown_until: Dict[str, int] = {}

    def decide_economic_action(self, actor: "Actor") -> Optional[EconomicCommand]:
        """Decide which economic action to take this turn."""
        # Shared with decide_market_actions later this turn; see BrainCache.
        cache = self._turn_cache(actor)

        # 1% chance per turn to re-evaluate the recipe.
        self.turns_since_recipe_evaluation += 1
        if self._should_reevaluate_recipe():
            self._adopt_recipe(self._select_new_recipe(actor, cache))
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
                    self._adopt_recipe(None)
            self.turns_since_recipe_evaluation = 0

        # Drop a line that cannot be run at all, not just one that is
        # unprofitable: the exit check above only fires on a negative score,
        # so a recipe scoring well but permanently missing an input is held
        # forever while the actor falls through to government work.
        if self.chosen_recipe_id:
            self._update_stuck_tracking(actor)

        if not self.chosen_recipe_id:
            self._adopt_recipe(self._select_new_recipe(actor, cache))
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

        # Everything else the actor is sitting on. Recipes are abandoned on
        # loss or when they get stuck, and the stock produced under the old
        # line would otherwise never be listed again: the recipe sweep only
        # offers the outputs of the CURRENT recipe. Without this the goods
        # pile up in producer inventories and the market shows no ask.
        commands.extend(self._liquidation_commands(actor, market, cache))

        return commands

    def _liquidation_commands(
        self, actor: "Actor", market: "Market", cache: Optional[BrainCache] = None
    ) -> List[MarketCommand]:
        """Offer held goods the actor has no remaining use for.

        Runs every turn, with or without a chosen recipe. Retained are the
        current recipe's inputs, tools and facility build materials, personal
        drive stock up to each drive's target, and the small working buffer in
        ``NON_DRIVE_KEEP_LEVELS``. The current recipe's outputs are skipped
        because ``_get_recipe_trading_commands`` already offers them, and two
        sell orders for one commodity in one turn would double-count the
        inventory.
        """
        reserved = self._reserved_commodity_ids(actor)
        keep_levels = self._keep_levels_by_commodity(actor)
        commands: List[MarketCommand] = []
        for commodity in actor.sim.commodity_registry.all_commodities():
            if not commodity.transportable or commodity.id in reserved:
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

    def _reserved_commodity_ids(self, actor: "Actor") -> set[str]:
        """Commodity ids the liquidation sweep must not offer.

        The chosen recipe's inputs, tools and outputs, plus the inputs and
        tools of the build process for any facility it still needs, so an
        actor assembling a facility does not sell the bricks it is collecting.
        """
        if self.chosen_recipe_id is None:
            return set()
        process = actor.sim.process_registry.get_process(self.chosen_recipe_id)
        if not process:
            return set()

        reserved = {commodity.id for commodity, _ in process.requirements}
        reserved.update(commodity.id for commodity in process.outputs)
        for facility in process.facilities_required:
            if actor.inventory.has_quantity(facility, 1):
                continue
            build_process_id = self._get_build_process_for_facility(facility)
            if not build_process_id:
                continue
            build_process = actor.sim.process_registry.get_process(build_process_id)
            if not build_process:
                continue
            reserved.update(commodity.id for commodity, _ in build_process.requirements)
        return reserved

    def _keep_levels_by_commodity(self, actor: "Actor") -> Dict[str, int]:
        """Inventory to retain per commodity id before offering the surplus.

        Drive materials are kept to the drive's target; the rest fall back to
        ``NON_DRIVE_KEEP_LEVELS``. First drive listing a material wins, which
        matches the colonist sweep.
        """
        levels: Dict[str, int] = {}
        for drive in actor.drives:
            target = drive.target_units()
            for material in drive.materials():
                levels.setdefault(material.id, target)
        for commodity_id, keep in NON_DRIVE_KEEP_LEVELS.items():
            levels.setdefault(commodity_id, keep)
        return levels

    def _should_reevaluate_recipe(self) -> bool:
        """1% chance per turn to re-evaluate the recipe choice."""
        return random.random() < 0.01

    def _adopt_recipe(self, recipe_id: Optional[str]) -> None:
        """Switch to ``recipe_id`` and reset the stuck tracker."""
        self.chosen_recipe_id = recipe_id
        self.stuck_turns = 0
        self.stuck_signature = None

    def _requirement_signature(
        self, actor: "Actor", process: "ProcessDefinition"
    ) -> tuple[tuple[str, int], ...]:
        """Inventory of everything ``process`` needs, including a facility build.

        The signature is the progress measure for the stuck check. It covers
        the recipe's own inputs, tools and facilities, plus the inputs and
        tools of the build process for any facility the actor still lacks, so
        an actor slowly assembling bricks for a chemistry lab reads as making
        progress rather than as stuck.
        """
        requirements = list(process.requirements)
        for facility in process.facilities_required:
            if actor.inventory.has_quantity(facility, 1):
                continue
            build_process_id = self._get_build_process_for_facility(facility)
            if not build_process_id:
                continue
            build_process = actor.sim.process_registry.get_process(build_process_id)
            if build_process:
                requirements.extend(build_process.requirements)
        get_quantity = actor.inventory.get_quantity
        return tuple(sorted({(c.id, get_quantity(c)) for c, _ in requirements}))

    def _update_stuck_tracking(self, actor: "Actor") -> None:
        """Abandon the chosen recipe if it has been unrunnable and static.

        Clears ``chosen_recipe_id`` and puts the recipe on cooldown once it
        has failed ``can_execute`` for ``RECIPE_STUCK_TURNS`` consecutive
        turns without the inventory of anything it needs moving.
        """
        if self.chosen_recipe_id is None:
            return
        process = actor.sim.process_registry.get_process(self.chosen_recipe_id)
        if not process:
            self._adopt_recipe(None)
            return

        if actor.can_execute(process):
            self.stuck_turns = 0
            self.stuck_signature = None
            return

        signature = self._requirement_signature(actor, process)
        if signature != self.stuck_signature:
            self.stuck_signature = signature
            self.stuck_turns = 0
            return

        self.stuck_turns += 1
        if self.stuck_turns >= RECIPE_STUCK_TURNS:
            self.recipe_cooldown_until[process.id] = (
                actor.sim.current_turn + RECIPE_COOLDOWN_TURNS
            )
            self._adopt_recipe(None)

    def _recipes_on_cooldown(self, actor: "Actor") -> set[str]:
        """Recipe ids still excluded after being abandoned as unrunnable."""
        if not self.recipe_cooldown_until:
            return set()
        current_turn = actor.sim.current_turn
        expired = [
            pid
            for pid, until in self.recipe_cooldown_until.items()
            if until <= current_turn
        ]
        for pid in expired:
            del self.recipe_cooldown_until[pid]
        return set(self.recipe_cooldown_until)

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
        on_cooldown = self._recipes_on_cooldown(actor)
        for process in actor.sim.process_registry.all_processes():
            if process.id in on_cooldown:
                continue
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

        total_output_value = self._recipe_output_value(actor, market, process, memo)
        if math.isnan(total_output_value):
            return 0.0

        # Entry requires ENTRY_MARGIN over costs, which include labor. Exit
        # checks skip the margin.
        if (
            require_entry_margin
            and total_output_value < total_input_cost * ENTRY_MARGIN
        ):
            return 0.0

        return total_output_value - total_input_cost

    def _recipe_output_value(
        self,
        actor: "Actor",
        market: "Market",
        process: "ProcessDefinition",
        memo: Dict[str, float],
    ) -> float:
        """Value of one run's outputs, scaled by local resource availability.

        Outputs are not imputed. Value is realized only if a real buyer bids,
        and the market maker bids on every transportable good, so an
        unsellable output is worthless to this actor. Returns ``math.nan``
        when any transportable output prices at or below zero, which callers
        read as "this recipe produces nothing worth having here".

        Shared by ``_calculate_recipe_score`` and the netback ceiling on
        procurement bids, so an actor pays for inputs on the same valuation
        that made it pick the recipe.
        """
        attribute_modifier = 1.0
        if process.resource_attribute and actor.planet:
            attribute_modifier = actor.planet.attributes.get_availability(
                process.resource_attribute.commodity
            )

        total = 0.0
        for commodity, quantity in process.outputs.items():
            # Non-transportable outputs are facilities for personal use; give
            # them a notional value for enabling other recipes.
            if not commodity.transportable:
                total += FACILITY_NOTIONAL_VALUE * quantity
                continue

            expected_quantity = quantity * attribute_modifier
            price = self._output_unit_value(
                actor, market, commodity, expected_quantity, memo
            )
            if price <= 0:
                return math.nan
            total += price * expected_quantity
        return total

    def _output_unit_value(
        self,
        actor: "Actor",
        market: "Market",
        commodity: "CommodityDefinition",
        expected_quantity: float,
        memo: Dict[str, float],
    ) -> float:
        """Price per unit this actor can realistically get for a recipe output.

        Entry scoring and the exit-on-loss check both come here, so a
        producer leaves a line on the same valuation that would have kept it
        out.

        The top of book overstates demand for a thin market. A market maker
        seeds an illiquid good with one-unit probes an order of magnitude
        above fair value; read as the price of a whole run they pull the
        population into producing something nobody buys. So how much of the
        book to believe depends on how much the good actually trades:

        1. Liquid good, one whose recent turnover already exceeds this run's
           output: the top bid is backed by flow, and is used as is.
        2. Thin good: the mean fill price of sweeping the book for the run,
           with each level clipped at the higher of the level that absorbs
           the run and ``NEVER_TRADED_VALUE_CAP`` over make cost. A lone
           discovery probe far above cost is clipped to the real demand
           under it; two real bids from a downstream producer over a
           1-credit floor are not thrown away, which valuing at the last
           level hit did (rare earth scored -273 under a live 321 bid).
        3. Thin good with a book too shallow to absorb a run at all: recent
           traded price. It sells, just not this much right now.
        4. Never traded: the only demand signal is a buyer's resting
           procurement bid, so it is honoured, but capped at a margin over
           what the good costs to make. That admits the bootstrap bid
           ``_buy_command`` rests for a cold-start intermediate, which is
           priced off the same imputation, while a discovery probe far above
           any production cost is not mistaken for demand. Refusing to value
           this case at all would re-open the producer/consumer standoff (see
           the decision log).
        """
        horizon = max(
            MIN_OUTPUT_DEPTH_UNITS,
            math.ceil(expected_quantity * OUTPUT_SALES_HORIZON_RUNS),
        )
        bid, _ = market.get_bid_ask_spread(commodity)

        if bid is not None and market.get_30_day_average_volume(commodity) >= horizon:
            return float(bid)

        depth_price = market.get_bid_price_at_depth(commodity, horizon)
        if depth_price is not None:
            imputed = self._imputed_unit_cost(
                actor, market, commodity, 0, frozenset(), memo, make_only=True
            )
            clip = float(depth_price)
            if not math.isinf(imputed):
                clip = max(clip, imputed * NEVER_TRADED_VALUE_CAP)
            sweep_price = market.get_bid_sweep_average(commodity, horizon, clip)
            return float(depth_price) if sweep_price is None else sweep_price

        if market.has_price_signal(commodity):
            return market.get_30_day_average_price(commodity)

        reference = (
            float(bid) if bid is not None else float(market.get_avg_price(commodity))
        )
        imputed = self._imputed_unit_cost(
            actor, market, commodity, 0, frozenset(), memo
        )
        if math.isinf(imputed):
            return reference
        return min(reference, imputed * NEVER_TRADED_VALUE_CAP)

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
        ceiling: float = math.inf,
    ) -> List[MarketCommand]:
        """Acquire ``quantity_to_buy`` units of ``commodity``.

        Lifts the cheapest resting ask, or, if none exists, rests a bid so a
        seller can find us. Resting a bid without a pre-existing ask breaks
        the producer/consumer standoff on never-traded intermediates: a
        medicine maker must signal demand for refined_chemicals before any
        refiner will produce them.

        ``ceiling`` is the netback value of one unit to this actor, from
        ``_input_price_ceiling``. With one, the resting bid starts at the
        reference price and escalates toward the ceiling with the market's
        scarcity pressure, and never exceeds it. ``math.inf`` means the
        netback could not be computed, and the older single-layer pricing
        applies: the reference price, bumped once by
        ``PROCUREMENT_BOOTSTRAP_MARGIN`` for a never-traded good or a stalled
        market.

        A resting ask is lifted at the ask either way. The ceiling does not
        bound it: callers rely on this to take supply that is already there.
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
        elif not math.isinf(ceiling):
            memo = cache.imputed_cost if cache is not None else {}
            reference = self._procurement_reference(actor, market, commodity, memo)
            pressure = market.scarcity_pressure_for(commodity)
            price = min(int(ceiling), math.ceil(reference * (1.0 + pressure)))
        elif market.has_price_signal(commodity):
            # A real trade price exists, possibly stale. Anchor to it.
            price = market.get_avg_price(commodity)
            if self._market_is_stalled(market, commodity):
                # The good has traded, but not lately, nothing is offered, and
                # demand has gone chronically unmet: the average is a fossil.
                # A bid resting at it leaves every supplier's 1.2x entry
                # threshold uncleared -- suppliers impute this good's cost from
                # the same average -- so the tier stays dead at a price that
                # looks live. Escalate by the same bootstrap margin a
                # never-traded input gets. (Imputation is not consulted: with a
                # price signal and no ask it resolves to this average anyway.)
                # Gated rather than unconditional, because applied to goods
                # that do have supply this only bids prices up.
                price = math.ceil(price * PROCUREMENT_BOOTSTRAP_MARGIN)
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

    def _procurement_reference(
        self,
        actor: "Actor",
        market: "Market",
        commodity: "CommodityDefinition",
        memo: Dict[str, float],
    ) -> float:
        """Price a resting procurement bid escalates from.

        The trade average where one exists. A never-traded good has none, and
        ``get_avg_price`` would return its fabricated default of 10, which
        sits below a rational seller's replacement-cost floor; that case
        anchors on our own imputed cost plus the bootstrap margin instead, so
        even at zero pressure the opening bid clears a supplier's entry
        threshold. Falls back to the fabricated default when the good cannot
        be imputed at all.
        """
        if market.has_price_signal(commodity):
            return float(market.get_avg_price(commodity))
        imputed = self._imputed_unit_cost(
            actor, market, commodity, 0, frozenset(), memo
        )
        if math.isinf(imputed):
            return float(market.get_avg_price(commodity))
        return imputed * PROCUREMENT_BOOTSTRAP_MARGIN

    def _input_price_ceiling(
        self,
        actor: "Actor",
        market: "Market",
        commodity: "CommodityDefinition",
        quantity_per_run: float,
        output_value: float,
        recipe_cost: float,
        memo: Dict[str, float],
        max_cost_multiple: float = math.inf,
    ) -> float:
        """Most this actor can pay per unit of ``commodity`` and still enter.

        ``output_value`` and ``recipe_cost`` are one run of the chosen recipe,
        from ``_recipe_output_value`` and ``_impute_recipe_cost``.
        ``quantity_per_run`` is how much of ``commodity`` that run consumes;
        for a material of a facility build it is the build quantity divided by
        the amortization horizon, matching how ``_impute_recipe_cost``
        amortizes the build.

        Substituting our own imputed unit cost out of the recipe cost leaves
        every other cost of the run, so the difference from the output value
        is what the whole input draw can be worth. Dividing by
        ``ENTRY_MARGIN`` keeps the recipe entry-profitable after paying it.
        ``max_cost_multiple`` bounds the result at that multiple of the
        input's recipe cost, imputed from its own recipe rather than its
        market quotes so the bound does not rise with the bids it permits;
        facility build materials pass ``BUILD_INPUT_CEILING_CAP``. A good
        with no recipe here falls back to its market-imputed cost.

        Returns ``math.inf`` when the netback cannot be computed or comes out
        non-positive; ``_buy_command`` reads that as "no ceiling" and prices
        the bid the older way.
        """
        if quantity_per_run <= 0 or math.isnan(output_value):
            return math.inf
        if math.isinf(recipe_cost):
            return math.inf
        unit_cost = self._imputed_unit_cost(
            actor, market, commodity, 0, frozenset(), memo
        )
        if math.isinf(unit_cost):
            return math.inf
        other_costs = recipe_cost - quantity_per_run * unit_cost
        ceiling = (output_value - other_costs) / (quantity_per_run * ENTRY_MARGIN)
        if ceiling <= 0:
            return math.inf
        if math.isinf(max_cost_multiple):
            return ceiling
        make_cost = self._imputed_unit_cost(
            actor, market, commodity, 0, frozenset(), memo, make_only=True
        )
        anchor = unit_cost if math.isinf(make_cost) else make_cost
        return min(ceiling, anchor * max_cost_multiple)

    @staticmethod
    def _market_is_stalled(market: "Market", commodity: "CommodityDefinition") -> bool:
        """Whether a good with trade history has become unobtainable here.

        Callers have already established there is no resting ask. Stalled
        means demand for it has gone chronically unmet and recent turnover has
        stopped, which together separate a dead tier from a good that is
        merely momentarily unoffered.
        """
        return (
            market.scarcity_pressure_for(commodity) >= PROCUREMENT_STALL_PRESSURE
            and market.get_30_day_average_volume(commodity) < PROCUREMENT_STALL_VOLUME
        )

    def _sell_command(
        self,
        actor: "Actor",
        market: "Market",
        commodity: "CommodityDefinition",
        cache: Optional[BrainCache] = None,
    ) -> List[MarketCommand]:
        """Sell the surplus of ``commodity``, floored at replacement cost.

        Retains the same keep level the liquidation sweep uses, so a producer
        does not list the stock its own drives are about to bid for. A
        make_food industrialist otherwise offered every unit it produced while
        ``_drive_buy_commands`` bid for food it was short of, and the two
        orders crossed against each other.

        Skips non-transportable goods; facilities are not tradable.
        """
        if not commodity.transportable:
            return []
        available = actor.inventory.get_available_quantity(commodity)
        keep = self._keep_levels_by_commodity(actor).get(commodity.id, 0)
        return self._sell_at_or_above_cost(
            actor, market, commodity, available - keep, cache
        )

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

        # Netback inputs to the recipe's own economics, recomputed every turn
        # from live market state. Both terms are one run of the recipe.
        memo: Dict[str, float] = cache.imputed_cost if cache is not None else {}
        output_value = self._recipe_output_value(actor, market, process, memo)
        recipe_cost = self._impute_recipe_cost(
            actor, market, process, 0, frozenset(), memo
        )

        for commodity, needed_quantity in process.inputs.items():
            current_quantity = actor.inventory.get_quantity(commodity)
            ceiling = self._input_price_ceiling(
                actor,
                market,
                commodity,
                float(needed_quantity),
                output_value,
                recipe_cost,
                memo,
            )
            commands.extend(
                self._buy_command(
                    actor,
                    market,
                    commodity,
                    needed_quantity - current_quantity,
                    cache,
                    ceiling,
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
                # A build material's share of one run is its build quantity
                # spread over the amortization horizon, matching how
                # _impute_recipe_cost charges the build, capped at
                # BUILD_INPUT_CEILING_CAP times the material's own cost. Tools
                # the build needs but does not consume have no such share and
                # keep the older pricing.
                build_quantity = build_process.inputs.get(commodity, 0)
                ceiling = self._input_price_ceiling(
                    actor,
                    market,
                    commodity,
                    build_quantity / self.facility_amortization_horizon,
                    output_value,
                    recipe_cost,
                    memo,
                    BUILD_INPUT_CEILING_CAP,
                )
                commands.extend(
                    self._buy_command(
                        actor,
                        market,
                        commodity,
                        needed_quantity - current_quantity,
                        cache,
                        ceiling,
                    )
                )

        for commodity, _ in process.outputs.items():
            commands.extend(self._sell_command(actor, market, commodity, cache))

        return commands
