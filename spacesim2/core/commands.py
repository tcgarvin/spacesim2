import random
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import TYPE_CHECKING, Dict, List, Tuple, cast

if TYPE_CHECKING:
    from spacesim2.core.actor import Actor
    from spacesim2.core.commodity import CommodityDefinition
    from spacesim2.core.market import Market, MarketParticipant


class Command(ABC):
    """Base class for all commands."""

    @abstractmethod
    def execute(self, actor: "Actor") -> bool:
        """Execute the command on the given actor.

        Args:
            actor: The actor to execute the command on

        Returns:
            bool: True if command executed successfully, False otherwise
        """
        pass


class EconomicCommand(Command):
    """Base class for economic action commands."""

    pass


class MarketCommand(Command):
    """Base class for market action commands."""

    pass


class ProcessCommand(EconomicCommand):
    """Command to execute a production process."""

    def __init__(self, process_id: str) -> None:
        self.process_id = process_id

    def __repr__(self) -> str:
        return f"ProcessCommand(process_id={self.process_id!r})"

    def execute(self, actor: "Actor") -> bool:
        """Execute a production process.

        Returns:
            bool: True if process was executed successfully, False otherwise
        """
        process = actor.sim.process_registry.get_process(self.process_id)
        if not process:
            return False

        # Check if actor has required inputs
        for commodity, quantity in process.inputs.items():
            if not actor.inventory.has_quantity(commodity, quantity):
                return False

        # Check if actor has required tools
        for tool in process.tools_required:
            if not actor.inventory.has_quantity(tool, 1):
                return False

        # Check if actor has access to required facilities in their inventory
        for facility in process.facilities_required:
            if not actor.inventory.has_quantity(facility, 1):
                return False

        # Perform skill check if process has relevant skills
        success = True
        multiplier = 1

        if process.relevant_skills:
            # Get skill ratings for all relevant skills
            skill_ratings = []
            for skill_id in process.relevant_skills:
                skill_rating = actor.get_skill_rating(skill_id)
                skill_ratings.append(skill_rating)

            # Calculate combined skill rating
            from spacesim2.core.skill import SkillCheck

            combined_rating = SkillCheck.get_combined_skill_rating(skill_ratings)

            # Perform success check
            success = SkillCheck.success_check(combined_rating)

            # If successful, check for multiplier
            if success and SkillCheck.multiplier_check(combined_rating):
                multiplier = 2  # Apply ×2 multiplier

        # If the process failed the skill check nothing happens
        if not success:
            # Record failure
            actor.last_action = f"Failed process: {process.name}"
            return False

        # Check planet resource availability if process has resource_attribute
        planet_multiplier = 1.0
        if process.resource_attribute and actor.planet and actor.planet.attributes:
            availability = actor.planet.attributes.get_availability(
                process.resource_attribute.commodity
            )

            if process.resource_attribute.effect == "success":
                # Availability affects whether process works at all
                if random.random() > availability:
                    actor.last_action = (
                        f"Failed {process.name}: insufficient planetary resources"
                    )
                    return False
            elif process.resource_attribute.effect == "output":
                # Availability scales output quantity
                planet_multiplier = availability

        # Process successful, apply multiplier
        # Consume inputs (multiplied if skill multiplier > 1)
        for commodity, quantity in process.inputs.items():
            actor.inventory.remove_commodity(commodity, quantity * multiplier)

        # Add outputs (apply both skill and planet multipliers)
        for commodity, quantity in process.outputs.items():
            # Combine skill multiplier (int, 1 or 2) with planet multiplier (float, 0-1)
            output_quantity = max(1, round(quantity * multiplier * planet_multiplier))
            actor.inventory.add_commodity(commodity, output_quantity)

        # Improve skills used in the process
        if process.relevant_skills:
            # Small skill improvement (0.01-0.03) for successful process execution
            skill_improvement = 0.01 + (
                0.02 * (multiplier - 1)
            )  # More improvement with multiplier
            for skill_id in process.relevant_skills:
                actor.improve_skill(skill_id, skill_improvement)

        # Tool degradation: 1% chance per tool to break after successful use
        TOOL_BREAK_PROBABILITY = 0.01
        for tool in process.tools_required:
            if random.random() < TOOL_BREAK_PROBABILITY:
                actor.inventory.remove_commodity(tool, 1)
                if actor.sim.data_logger:
                    # Handle both CommodityDefinition objects and string IDs
                    tool_name = tool.name if hasattr(tool, "name") else str(tool)
                    actor.sim.data_logger.log_actor_note(
                        actor, f"Tool broke: {tool_name}"
                    )

        # Record action
        modifiers = []
        if multiplier > 1:
            modifiers.append(f"skill ×{multiplier}")
        if planet_multiplier < 1.0:
            modifiers.append(f"planet {planet_multiplier:.0%}")
        modifier_text = f" ({', '.join(modifiers)})" if modifiers else ""
        actor.last_action = f"Executed process: {process.name}{modifier_text}"
        return True


GOVERNMENT_WAGE = 10


class GovernmentWorkCommand(EconomicCommand):
    """Command to perform government work for a wage."""

    def __repr__(self) -> str:
        return f"GovernmentWorkCommand(wage={GOVERNMENT_WAGE})"

    def execute(self, actor: "Actor") -> bool:
        """Perform government work to earn a fixed wage."""
        actor.money += GOVERNMENT_WAGE
        actor.last_action = f"Government work for {GOVERNMENT_WAGE} credits"
        return True


class CancelOrderCommand(MarketCommand):
    """Command to cancel a market order."""

    def __init__(self, order_id: str) -> None:
        self.order_id = order_id

    def __repr__(self) -> str:
        return f"CancelOrderCommand(order_id={self.order_id!r})"

    def execute(self, actor: "Actor") -> bool:
        """Cancel a market order."""
        if not actor.planet:
            return False

        return actor.planet.market.cancel_order(self.order_id)


class PlaceBuyOrderCommand(MarketCommand):
    """Command to place a buy order on the market."""

    def __init__(
        self, commodity_type: "CommodityDefinition", quantity: int, price: int
    ) -> None:
        self.commodity_type = commodity_type
        self.quantity = quantity
        self.price = price

    def __repr__(self) -> str:
        return f"PlaceBuyOrderCommand(commodity={self.commodity_type.id!r}, quantity={self.quantity}, price={self.price})"

    def execute(self, actor: "Actor") -> bool:
        """Place a buy order on the market."""
        if not actor.planet:
            return False

        order_id = actor.planet.market.place_buy_order(
            actor, self.commodity_type, self.quantity, self.price
        )

        if order_id:
            commodity_name = self.commodity_type.id
            actor.active_orders[order_id] = f"buy {commodity_name}"
            return True

        return False


class PlaceSellOrderCommand(MarketCommand):
    """Command to place a sell order on the market."""

    def __init__(
        self, commodity_type: "CommodityDefinition", quantity: int, price: int
    ) -> None:
        self.commodity_type = commodity_type
        self.quantity = quantity
        self.price = price

    def __repr__(self) -> str:
        return f"PlaceSellOrderCommand(commodity={self.commodity_type.id!r}, quantity={self.quantity}, price={self.price})"

    def execute(self, actor: "Actor") -> bool:
        """Place a sell order on the market."""
        if not actor.planet:
            return False

        order_id = actor.planet.market.place_sell_order(
            actor, self.commodity_type, self.quantity, self.price
        )

        if order_id:
            commodity_name = self.commodity_type.id
            actor.active_orders[order_id] = f"sell {commodity_name}"
            return True

        return False


# Identity of an open order for churn pruning: side, commodity, price, quantity.
_OrderKey = Tuple[bool, str, int, int]


def prune_unchanged_order_commands(
    market: "Market",
    actor: "MarketParticipant",
    commands: List[MarketCommand],
) -> List[MarketCommand]:
    """Drop cancel+repost pairs that would recreate an identical order.

    Every actor brain rebuilds its whole book each turn (cancel everything,
    repost the desired quotes), and measurement shows ~two-thirds of those
    cancels are followed the same turn by a repost with identical side,
    commodity, price, AND quantity. Executing such a pair is a no-op for
    market state — cancel refunds exactly what the repost re-reserves, and no
    other actor acts between the two commands — so both commands can be
    dropped and the standing order kept.

    Pairing on full identity keeps this behavior-safe: a kept buy/sell order
    holds the same reservation the repost would take, so later commands in the
    list see the same money/inventory. Kept orders get their timestamp
    refreshed to the current turn, exactly as the repost would have stamped it
    — without this, stable quotes (market makers) silently gain permanent
    price-time priority over drive bids whose quantities drift, which
    measurably starved the thin medicine market. Same-timestamp ties are
    broken randomly at match time (see ``_match_orders_for_commodity``),
    mirroring the rotation the per-turn actor shuffle used to provide.

    Only cancels of ``actor``'s own orders in ``market`` are eligible; anything
    unmatched passes through untouched, in the original relative order.
    """
    # Exact-class checks (not isinstance): these run for every command of
    # every actor-turn, and isinstance on ABC-derived classes routes through
    # abc.__instancecheck__, which showed up in profiles. No command class
    # here is ever subclassed.
    cancels_by_key: Dict[_OrderKey, List[CancelOrderCommand]] = defaultdict(list)
    for command in commands:
        if command.__class__ is CancelOrderCommand:
            command = cast(CancelOrderCommand, command)
            order = market.orders_by_id.get(command.order_id)
            if order is not None and order.actor is actor:
                key = (
                    order.is_buy,
                    order.commodity_type.id,
                    order.price,
                    order.quantity,
                )
                cancels_by_key[key].append(command)

    if not cancels_by_key:
        return commands

    dropped: set = set()
    for command in commands:
        command_class = command.__class__
        is_buy = command_class is PlaceBuyOrderCommand
        if is_buy or command_class is PlaceSellOrderCommand:
            command = cast("PlaceBuyOrderCommand | PlaceSellOrderCommand", command)
            key = (
                is_buy,
                command.commodity_type.id,
                command.price,
                command.quantity,
            )
            matching_cancels = cancels_by_key.get(key)
            if matching_cancels:
                cancel = matching_cancels.pop()
                dropped.add(id(cancel))
                dropped.add(id(command))
                # Stamp the kept order as if it had been reposted this turn.
                market.orders_by_id[cancel.order_id].timestamp = market.current_turn

    if not dropped:
        return commands
    return [c for c in commands if id(c) not in dropped]
