import math
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from spacesim2.core.commands import (
    EconomicCommand,
    MarketCommand,
    PlaceBuyOrderCommand,
    PlaceSellOrderCommand,
)
from spacesim2.core.skill import SkillCheck

if TYPE_CHECKING:
    from spacesim2.core.actor import Actor
    from spacesim2.core.commodity import CommodityDefinition
    from spacesim2.core.drives.actor_drive import ActorDrive
    from spacesim2.core.market import Market
    from spacesim2.core.process import ProcessDefinition

# Opportunity cost floor for a turn of labor (government work wage). Used as the
# labor component of replacement cost when self-producing a good.
GOVERNMENT_WAGE = 10

# Tools wear out after ~100 uses; amortize their cost across that lifespan.
TOOL_EXPECTED_LIFESPAN = 100

# Numeraire drive: marginal value of money is anchored on food, the most basic
# survival good. Willingness-to-pay for every other drive good is expressed
# relative to it.
NUMERAIRE_DRIVE = "food"

# Bound on how deep make-or-buy imputation recurses through production chains.
MAX_IMPUTE_DEPTH = 6

# Default facility amortization horizon for actors that don't set their own
# (industrialists randomize a per-actor value to encode risk appetite; see
# brains/industrialist.py). Used when imputation must amortize a lump-sum
# facility build cost into a per-run cost.
DEFAULT_FACILITY_AMORTIZATION_HORIZON = 300


class BrainCache:
    """Per-actor-turn memoization for market quotes and cost/yield math.

    Each brain owns one ``BrainCache`` (created lazily by
    ``ActorBrain._turn_cache``) that lives for a whole actor-turn — i.e.
    across both ``decide_economic_action`` and ``decide_market_actions``.

    **Invalidation rule.** ``refresh`` compares a snapshot key on every
    top-level ``decide_*`` entry:

    * ``sim.current_turn`` changed -> everything is cleared. Between sim
      turns other actors trade, orders match, and prices move, so nothing
      cached here survives a turn boundary.
    * Same turn but the actor's state key ``(id(actor), inventory.version,
      skills_version)`` changed -> only the actor-state group is cleared.
      Within one actor-turn the *market* never mutates between the two
      ``decide_*`` calls (``Actor.take_turn`` executes the economic command
      in between, and economic commands touch only inventory/skills/money,
      never the order books), so quotes stay valid; but a ``ProcessCommand``
      does change inventory and skills, which is exactly what the version
      counters detect.

    Cached values fall into two groups:

    * Market-derived, valid for the whole sim turn: ``bid_ask``,
      ``avg_price``, and ``yield_modifier`` (planet attributes are fixed for
      the run; scoped per turn only to keep lifetime rules uniform).
    * Actor-state-derived, additionally invalidated when inventory or skills
      change: ``skill_factor``, ``replacement_cost``, ``imputed_cost``, and
      ``best_result`` (they read tool/facility ownership, skill ratings, or
      ``can_execute_process``).

    Money and drive metrics are deliberately *not* cached anywhere here, so
    they need no versioning. Keys are commodity/process ``id`` strings.
    """

    __slots__ = (
        "bid_ask",
        "avg_price",
        "yield_modifier",
        "skill_factor",
        "replacement_cost",
        "imputed_cost",
        "best_result",
        "_turn",
        "_actor_key",
    )

    def __init__(self) -> None:
        self._turn: int = -1
        self._actor_key: Tuple[int, int, int] = (-1, -1, -1)
        self._reset_market_group()
        self._reset_actor_group()

    def _reset_market_group(self) -> None:
        self.bid_ask: Dict[str, Tuple[Optional[int], Optional[int]]] = {}
        self.avg_price: Dict[str, float] = {}
        self.yield_modifier: Dict[str, float] = {}

    def _reset_actor_group(self) -> None:
        self.skill_factor: Dict[str, float] = {}
        self.replacement_cost: Dict[str, Optional[float]] = {}
        # Shared memo for make-or-buy imputation (see _imputed_unit_cost).
        self.imputed_cost: Dict[str, float] = {}
        # Colonist-specific: memoized (best_process, raw_profit) for the
        # whole-registry profitability scan (see colonist.py).
        self.best_result: Optional[Tuple[Optional["ProcessDefinition"], float]] = None

    def refresh(self, actor: "Actor") -> "BrainCache":
        """Validate the cache against ``actor``'s current turn/state.

        Call at the top of every top-level ``decide_*`` call; see the class
        docstring for the invalidation rule. Returns ``self`` for chaining.
        """
        turn = actor.sim.current_turn
        actor_key = (id(actor), actor.inventory.version, actor.skills_version)
        if turn != self._turn:
            self._turn = turn
            self._actor_key = actor_key
            self._reset_market_group()
            self._reset_actor_group()
        elif actor_key != self._actor_key:
            self._actor_key = actor_key
            self._reset_actor_group()
        return self


def _get_bid_ask(
    market: "Market",
    commodity: "CommodityDefinition",
    cache: Optional[BrainCache],
) -> Tuple[Optional[int], Optional[int]]:
    """Cache-aware wrapper around ``market.get_bid_ask_spread``."""
    if cache is None:
        return market.get_bid_ask_spread(commodity)
    key = commodity.id
    if key not in cache.bid_ask:
        cache.bid_ask[key] = market.get_bid_ask_spread(commodity)
    return cache.bid_ask[key]


def _get_avg_price(
    market: "Market",
    commodity: "CommodityDefinition",
    cache: Optional[BrainCache],
) -> float:
    """Cache-aware wrapper around ``market.get_avg_price``."""
    if cache is None:
        return market.get_avg_price(commodity)
    key = commodity.id
    if key not in cache.avg_price:
        cache.avg_price[key] = market.get_avg_price(commodity)
    return cache.avg_price[key]


class ActorBrain:
    """Base class for actor decision making strategies."""

    # Subclasses may override per-instance (IndustrialistBrain randomizes it).
    facility_amortization_horizon: int = DEFAULT_FACILITY_AMORTIZATION_HORIZON

    # Per-brain memo cache; created lazily by _turn_cache. Class-level default
    # so subclasses need not call a base __init__.
    _cache: Optional[BrainCache] = None

    def _turn_cache(self, actor: "Actor") -> BrainCache:
        """The brain's per-actor-turn ``BrainCache``, freshly validated.

        Call once at the top of each ``decide_*`` entry point; the cache is
        created lazily on first use and invalidated per the rule documented
        on ``BrainCache``.
        """
        if self._cache is None:
            self._cache = BrainCache()
        return self._cache.refresh(actor)

    def decide_economic_action(self, actor: "Actor") -> Optional[EconomicCommand]:
        """Decide which economic action to take this turn."""
        raise NotImplementedError("Subclasses must implement this method")

    def decide_market_actions(self, actor: "Actor") -> List[MarketCommand]:
        """Decide what market actions to take this turn."""
        raise NotImplementedError("Subclasses must implement this method")

    # ------------------------------------------------------------------
    # Drive-backed demand: a generic willingness-to-pay for consumer goods.
    #
    # Two layers (see docs/needs.md): a stable WTP *ceiling* grounded in welfare
    # economics, and a posted *bid* that escalates from a modest reference price
    # toward that ceiling as the market's scarcity pressure grows. The ceiling
    # keeps bids from ever running into welfare-negative territory; the
    # escalation is what pulls imports to starved planets.
    # ------------------------------------------------------------------

    def _drive_buy_commands(
        self,
        actor: "Actor",
        market: "Market",
        cache: Optional[BrainCache] = None,
    ) -> List[MarketCommand]:
        """Place buy orders for drive materials, survival-first within budget.

        Drives are served in priority order (food first, then by marginal
        welfare). Each drive draws from a running budget so higher-priority
        needs get first claim on the actor's money.
        """
        if cache is None:
            cache = BrainCache()
        commands: List[MarketCommand] = []
        available = actor.money

        lam = self._value_of_money(actor, market, cache)
        if lam <= 0:
            return commands

        for drive in self._drives_by_priority(actor):
            mats = drive.materials()
            if not mats:
                continue

            have = sum(actor.inventory.get_quantity(m) for m in mats)
            need = drive.target_units() - have
            if need <= 0:
                continue

            target_commodity, ask = self._cheapest_material_ask(actor, market, mats)
            wtp = self._drive_willingness_to_pay(
                actor, market, drive, target_commodity, lam, cache
            )
            if wtp <= 0:
                continue

            if ask is not None and ask <= wtp:
                # Supply is present and affordable: take it at the ask.
                bid = ask
            else:
                # No affordable local supply: post a standing bid that escalates
                # toward the ceiling under scarcity pressure to attract imports.
                ref = self._drive_bid_reference(actor, market, target_commodity, cache)
                pressure = market.scarcity_pressure_for(target_commodity)
                bid = min(wtp, int(round(ref * (1.0 + pressure))))

            if bid <= 0:
                continue

            qty = min(need, available // bid)
            if qty > 0:
                commands.append(PlaceBuyOrderCommand(target_commodity, qty, bid))
                available -= qty * bid

        return commands

    def _drive_bid_reference(
        self,
        actor: "Actor",
        market: "Market",
        commodity: "CommodityDefinition",
        cache: Optional[BrainCache] = None,
    ) -> float:
        """Reference price a standing drive bid escalates from.

        For goods with a real trade history the backward-looking average is a
        sound anchor. For never-traded goods ``get_avg_price`` fabricates a
        default of 10, which pins bids below any rational producer's entry
        threshold and can deadlock a planet's cold start (the consumer-side
        twin of the producer-side fix in IndustrialistBrain._buy_command).
        Anchor those on the buyer's own imputed replacement cost instead, so
        scarcity pressure escalates bids from a level producers can actually
        respond to. Falls back to the fabricated default when the good cannot
        be imputed at all (no recipe reachable) - a floor beats no bid.
        """
        if market.has_price_signal(commodity):
            return float(market.get_avg_price(commodity))

        # Imputation recurses over the whole process graph and this runs every
        # turn for every actor with an unmet drive, so cache the anchor per
        # market/turn. The first asker's perspective (inventory, amortization
        # horizon) leaks into the shared value, but the anchor only needs to be
        # order-of-magnitude right: scarcity pressure and the WTP ceiling do
        # the fine-tuning.
        cached = market.drive_anchor_cache.get(commodity.id)
        if cached is not None and cached[0] == market.current_turn:
            return cached[1]
        memo = cache.imputed_cost if cache is not None else {}
        imputed = self._imputed_unit_cost(
            actor, market, commodity, 0, frozenset(), memo
        )
        anchor = (
            float(market.get_avg_price(commodity)) if math.isinf(imputed) else imputed
        )
        market.drive_anchor_cache[commodity.id] = (market.current_turn, anchor)
        return anchor

    def _drives_by_priority(self, actor: "Actor") -> List["ActorDrive"]:
        """Order drives so food (survival) comes first, then by marginal welfare."""

        def key(drive: "ActorDrive") -> Tuple[int, float]:
            is_numeraire = drive.metrics.get_name() == NUMERAIRE_DRIVE
            return (0 if is_numeraire else 1, -drive.marginal_welfare())

        return sorted(actor.drives, key=key)

    def _value_of_money(
        self,
        actor: "Actor",
        market: "Market",
        cache: Optional[BrainCache] = None,
    ) -> float:
        """Marginal welfare per unit of money, anchored on the food numeraire.

        lambda = marginal_welfare_food / price_food: the welfare a marginal
        dollar buys via its best survival use. As food security rises the food
        buffer discounts this, so money becomes "cheaper" and the actor will pay
        more for under-stocked drives. The food buffer is floored so lambda never
        collapses to zero; willingness-to-pay is additionally bounded above by
        replacement cost, which is the real guard against blow-up.
        """
        for drive in actor.drives:
            if drive.metrics.get_name() != NUMERAIRE_DRIVE:
                continue
            mats = drive.materials()
            if not mats:
                return 0.0
            price_food = self._effective_food_price(actor, market, mats[0], cache)
            if price_food <= 0:
                return 0.0
            # Floor the coverage discount so a hoarded pantry can't zero lambda.
            food_welfare = max(
                drive.marginal_welfare(), 0.1 * drive.deprivation_stake()
            )
            return food_welfare / price_food
        return 0.0

    def _effective_food_price(
        self,
        actor: "Actor",
        market: "Market",
        food: "CommodityDefinition",
        cache: Optional[BrainCache] = None,
    ) -> float:
        """The marginal cost of food for this actor: buy it or make it.

        Uses the live ask (what a unit costs right now) or the actor's own
        replacement cost, whichever is cheaper, falling back to the rolling
        average when neither exists. Anchoring lambda on the *backward-looking
        average* instead would make the numeraire's own willingness-to-pay
        degenerate to the last traded price, so hungry actors could never bid
        food up to what it is actually worth to them.
        """
        _, ask = _get_bid_ask(market, food, cache)
        replacement = self._replacement_cost(actor, market, food, cache)
        candidates = [float(price) for price in (ask, replacement) if price is not None]
        if candidates:
            return min(candidates)
        return float(_get_avg_price(market, food, cache))

    def _drive_willingness_to_pay(
        self,
        actor: "Actor",
        market: "Market",
        drive: "ActorDrive",
        commodity: "CommodityDefinition",
        lam: float,
        cache: Optional[BrainCache] = None,
    ) -> int:
        """Maximum price the actor would pay for one unit of a drive material.

        WTP = marginal_welfare / value_of_money, capped by the cost of producing
        the good locally (never pay more to import than to make it yourself).
        The cap is relaxed as drive debt accumulates: making it yourself is a
        long-run substitute, and an actor already going without can't produce
        fast enough for the cap to be real — they should accept a scarcity
        premium (up to 2x at full deprivation) rather than keep starving.
        """
        if lam <= 0:
            return 0
        welfare_wtp = drive.marginal_welfare() / lam

        replacement = self._replacement_cost(actor, market, commodity, cache)
        if replacement is not None:
            replacement *= 1.0 + drive.metrics.debt
        wtp = welfare_wtp if replacement is None else min(welfare_wtp, replacement)
        # Ceil so the ceiling lines up with sellers' (also ceiled) cost floor;
        # truncating would leave a permanent 1-credit gap that blocks trade
        # between actors with identical costs.
        return max(0, math.ceil(wtp))

    def _replacement_cost(
        self,
        actor: "Actor",
        market: "Market",
        commodity: "CommodityDefinition",
        cache: Optional[BrainCache] = None,
    ) -> Optional[float]:
        """Per-unit cost for *this actor* to self-produce a commodity.

        Considers only processes the actor could realistically run: required
        facilities must already be owned (a lump-sum facility build is not a
        substitute for one purchase), while missing tools are charged at an
        amortized share of their market price. Inputs are valued at local
        ask/avg prices; labor is one turn at the government wage scaled by the
        actor's expected skill throughput, and yield is discounted by planet
        resource availability. Skill and planet attributes make this cost
        differ per actor/planet — that heterogeneity is what keeps seller
        floors below buyer ceilings so trade can clear. Returns None when the
        actor has no way to make the good, in which case there is no
        make-it-yourself ceiling.

        Memoized per commodity in ``cache``; entries live until the turn ends
        or the actor's inventory/skills change (see ``BrainCache``).
        """
        if cache is not None and commodity.id in cache.replacement_cost:
            return cache.replacement_cost[commodity.id]

        best: Optional[float] = None
        for process in actor.sim.process_registry.get_processes_producing(commodity):
            out_qty = process.outputs.get(commodity, 0)
            if out_qty <= 0:
                continue
            if not all(
                actor.inventory.has_quantity(facility, 1)
                for facility in process.facilities_required
            ):
                continue

            input_cost = 0.0
            for input_commodity, qty in process.inputs.items():
                _, ask = _get_bid_ask(market, input_commodity, cache)
                price = (
                    ask
                    if ask is not None
                    else _get_avg_price(market, input_commodity, cache)
                )
                input_cost += price * qty
            for tool in process.tools_required:
                if actor.inventory.has_quantity(tool, 1):
                    continue
                _, ask = _get_bid_ask(market, tool, cache)
                price = ask if ask is not None else _get_avg_price(market, tool, cache)
                input_cost += price / TOOL_EXPECTED_LIFESPAN

            expected_out = out_qty * self._expected_yield_modifier(
                actor, process, cache
            )
            if expected_out <= 0:
                continue
            # Inputs are only consumed on success and scale with the output
            # multiplier, so per-unit input cost is independent of skill;
            # labor, by contrast, is spent on failed turns too.
            skill_factor = self._expected_skill_factor(actor, process, cache)
            per_unit = input_cost / expected_out + GOVERNMENT_WAGE / (
                expected_out * skill_factor
            )
            if best is None or per_unit < best:
                best = per_unit

        if cache is not None:
            cache.replacement_cost[commodity.id] = best
        return best

    def _expected_yield_modifier(
        self,
        actor: "Actor",
        process: "ProcessDefinition",
        cache: Optional[BrainCache] = None,
    ) -> float:
        """Expected output fraction given planet resource availability.

        Both attribute effects reduce expected yield proportionally: "output"
        scales the quantity, "success" scales the chance the run succeeds.

        Memoized per process in ``cache`` (see ``BrainCache``); a planet's
        attributes never change during a run, so this is even safe to reuse
        beyond a turn, but we scope it to the turn to keep cache lifetime
        rules uniform across all cached quantities.
        """
        if cache is not None and process.id in cache.yield_modifier:
            return cache.yield_modifier[process.id]

        if process.resource_attribute and actor.planet:
            value = actor.planet.attributes.get_availability(
                process.resource_attribute.commodity
            )
        else:
            value = 1.0

        if cache is not None:
            cache.yield_modifier[process.id] = value
        return value

    def _expected_skill_factor(
        self,
        actor: "Actor",
        process: "ProcessDefinition",
        cache: Optional[BrainCache] = None,
    ) -> float:
        """Expected output per turn of labor relative to a guaranteed run.

        Mirrors the skill check in ProcessCommand: ratings below 1.0 fail
        (and waste the turn) proportionally; ratings above 1.0 sometimes
        double the run. Always positive (ratings are clamped to >= 0.5).

        Memoized per process in ``cache``; entries are dropped whenever the
        actor's skills change (skill improvement bumps ``skills_version``
        when a ProcessCommand executes — see ``BrainCache``).
        """
        if cache is not None and process.id in cache.skill_factor:
            return cache.skill_factor[process.id]

        if not process.relevant_skills:
            value = 1.0
        else:
            rating = SkillCheck.get_combined_skill_rating(
                [
                    actor.get_skill_rating(skill_id)
                    for skill_id in process.relevant_skills
                ]
            )
            success_probability = min(1.0, rating)
            expected_multiplier = 1.0 + max(0.0, rating - 1.0) * 0.5
            value = success_probability * expected_multiplier

        if cache is not None:
            cache.skill_factor[process.id] = value
        return value

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
        #    Only trust the avg when a real trade has set it - otherwise
        #    get_avg_price returns its fabricated default of 10, which would
        #    short-circuit the recursive "make it" branch for never-traded goods
        #    with a bogus price (the exact cold-start deadlock we're fixing).
        _, ask = market.get_bid_ask_spread(commodity)
        if ask is not None:
            return float(ask)
        if market.has_price_signal(commodity):
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
        for process in actor.sim.process_registry.get_processes_producing(commodity):
            out_qty = 0
            for out_commodity, qty in process.outputs.items():
                if out_commodity.id == commodity.id:
                    out_qty = qty
                    break
            if out_qty <= 0:
                continue
            # Local resource availability scales expected yield: "output"
            # shrinks the quantity produced, "success" makes the whole turn
            # fail with probability (1 - attr). Either way the expected unit
            # cost divides by attr, so a resource-poor planet imputes
            # extraction as genuinely expensive instead of assuming full
            # yield (the mispricing that clustered refiners on ore-poor
            # planets).
            attribute_modifier = 1.0
            if process.resource_attribute and actor.planet:
                attribute_modifier = actor.planet.attributes.get_availability(
                    process.resource_attribute.commodity
                )
            if attribute_modifier <= 0.0:
                continue  # resource absent here -> can't make it locally
            recipe_cost = self._impute_recipe_cost(
                actor, market, process, depth, visiting, memo
            )
            if math.isinf(recipe_cost):
                continue
            best = min(best, recipe_cost / (out_qty * attribute_modifier))

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

    def _sell_at_or_above_cost(
        self,
        actor: "Actor",
        market: "Market",
        commodity: "CommodityDefinition",
        quantity: int,
        cache: Optional[BrainCache] = None,
    ) -> List[MarketCommand]:
        """Sell ``quantity`` units without dumping below replacement cost.

        Hits the best resting bid when it covers what it would cost this
        actor to remake the good; otherwise rests an ask at that cost so
        demand has to come up to meet real supply. Without this floor,
        price-taking sellers fill the market maker's 1-credit discovery
        probes and anchor the whole price level there.
        """
        if quantity <= 0:
            return []

        floor = self._replacement_cost(actor, market, commodity, cache)
        min_ask = 1 if floor is None else max(1, math.ceil(floor))

        bids = sorted(
            [o for o in market.buy_orders.get(commodity, []) if o.actor != actor],
            key=lambda o: (-o.price, o.timestamp),
        )
        if bids and bids[0].price >= min_ask:
            price = bids[0].price
        else:
            price = min_ask
        return [PlaceSellOrderCommand(commodity, quantity, price)]

    def _cheapest_material_ask(
        self,
        actor: "Actor",
        market: "Market",
        materials: List["CommodityDefinition"],
    ) -> Tuple["CommodityDefinition", Optional[int]]:
        """Find the cheapest available (non-own) ask among a drive's materials.

        Returns the chosen commodity and its ask price, or the basic material
        with ``None`` if nothing is for sale locally.
        """
        chosen = materials[0]
        best_ask: Optional[int] = None
        for commodity in materials:
            asks = [
                o.price
                for o in market.sell_orders.get(commodity, [])
                if o.actor != actor
            ]
            if asks:
                low = min(asks)
                if best_ask is None or low < best_ask:
                    best_ask = low
                    chosen = commodity
        return chosen, best_ask
