from typing import TYPE_CHECKING, List, Optional, Tuple

from spacesim2.core.commands import (
    EconomicCommand,
    MarketCommand,
    PlaceBuyOrderCommand,
)

if TYPE_CHECKING:
    from spacesim2.core.actor import Actor
    from spacesim2.core.commodity import CommodityDefinition
    from spacesim2.core.drives.actor_drive import ActorDrive
    from spacesim2.core.market import Market

# Opportunity cost floor for a turn of labor (government work wage). Used as the
# labor component of replacement cost when self-producing a good.
GOVERNMENT_WAGE = 10

# Numeraire drive: marginal value of money is anchored on food, the most basic
# survival good. Willingness-to-pay for every other drive good is expressed
# relative to it.
NUMERAIRE_DRIVE = "food"


class ActorBrain:
    """Base class for actor decision making strategies."""

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
        self, actor: "Actor", market: "Market"
    ) -> List[MarketCommand]:
        """Place buy orders for drive materials, survival-first within budget.

        Drives are served in priority order (food first, then by marginal
        welfare). Each drive draws from a running budget so higher-priority
        needs get first claim on the actor's money.
        """
        commands: List[MarketCommand] = []
        available = actor.money

        lam = self._value_of_money(actor, market)
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
                actor, market, drive, target_commodity, lam
            )
            if wtp <= 0:
                continue

            if ask is not None and ask <= wtp:
                # Supply is present and affordable: take it at the ask.
                bid = ask
            else:
                # No affordable local supply: post a standing bid that escalates
                # toward the ceiling under scarcity pressure to attract imports.
                ref = market.get_avg_price(target_commodity)
                pressure = market.scarcity_pressure_for(target_commodity)
                bid = min(wtp, int(round(ref * (1.0 + pressure))))

            if bid <= 0:
                continue

            qty = min(need, available // bid)
            if qty > 0:
                commands.append(PlaceBuyOrderCommand(target_commodity, qty, bid))
                available -= qty * bid

        return commands

    def _drives_by_priority(self, actor: "Actor") -> List["ActorDrive"]:
        """Order drives so food (survival) comes first, then by marginal welfare."""

        def key(drive: "ActorDrive") -> Tuple[int, float]:
            is_numeraire = drive.metrics.get_name() == NUMERAIRE_DRIVE
            return (0 if is_numeraire else 1, -drive.marginal_welfare())

        return sorted(actor.drives, key=key)

    def _value_of_money(self, actor: "Actor", market: "Market") -> float:
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
            price_food = market.get_avg_price(mats[0])
            if price_food <= 0:
                return 0.0
            # Floor the coverage discount so a hoarded pantry can't zero lambda.
            food_welfare = max(
                drive.marginal_welfare(), 0.1 * drive.deprivation_stake()
            )
            return food_welfare / price_food
        return 0.0

    def _drive_willingness_to_pay(
        self,
        actor: "Actor",
        market: "Market",
        drive: "ActorDrive",
        commodity: "CommodityDefinition",
        lam: float,
    ) -> int:
        """Maximum price the actor would pay for one unit of a drive material.

        WTP = marginal_welfare / value_of_money, capped by the cost of producing
        the good locally (never pay more to import than to make it yourself).
        """
        if lam <= 0:
            return 0
        welfare_wtp = drive.marginal_welfare() / lam

        replacement = self._replacement_cost(actor, market, commodity)
        wtp = welfare_wtp if replacement is None else min(welfare_wtp, replacement)
        return max(0, int(wtp))

    def _replacement_cost(
        self, actor: "Actor", market: "Market", commodity: "CommodityDefinition"
    ) -> Optional[float]:
        """Per-unit cost to self-produce a commodity at local input prices.

        Considers every process that outputs the commodity and returns the
        cheapest (inputs valued at local ask/avg price plus one turn of labor).
        Returns None if nothing produces it, in which case there is no
        make-it-yourself ceiling.
        """
        best: Optional[float] = None
        for process in actor.sim.process_registry.all_processes():
            out_qty = process.outputs.get(commodity, 0)
            if out_qty <= 0:
                continue

            input_cost = 0.0
            for input_commodity, qty in process.inputs.items():
                _, ask = market.get_bid_ask_spread(input_commodity)
                price = (
                    ask if ask is not None else market.get_avg_price(input_commodity)
                )
                input_cost += price * qty

            per_unit = (input_cost + GOVERNMENT_WAGE) / out_qty
            if best is None or per_unit < best:
                best = per_unit

        return best

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
