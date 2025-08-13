from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from spacesim2.core.actor import Actor
    from spacesim2.core.commodity import CommodityDefinition


class Command(ABC):
    """Base class for all commands."""
    
    @abstractmethod
    def execute(self, actor: 'Actor') -> bool:
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
    
    def execute(self, actor: 'Actor') -> bool:
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
        
        # Process successful, apply multiplier
        # Consume inputs (multiplied if multiplier > 1)
        for commodity, quantity in process.inputs.items():
            actor.inventory.remove_commodity(commodity, quantity * multiplier)
            
        # Add outputs (multiplied if multiplier > 1)
        for commodity, quantity in process.outputs.items():
            actor.inventory.add_commodity(commodity, quantity * multiplier)
            
        # Improve skills used in the process
        if process.relevant_skills:
            # Small skill improvement (0.01-0.03) for successful process execution
            skill_improvement = 0.01 + (0.02 * (multiplier - 1))  # More improvement with multiplier
            for skill_id in process.relevant_skills:
                actor.improve_skill(skill_id, skill_improvement)
        
        # Record action
        multiplier_text = f" (×{multiplier})" if multiplier > 1 else ""
        actor.last_action = f"Executed process: {process.name}{multiplier_text}"
        return True


GOVERNMENT_WAGE = 10
class GovernmentWorkCommand(EconomicCommand):
    """Command to perform government work for a wage."""
    
    def execute(self, actor: 'Actor') -> bool:
        """Perform government work to earn a fixed wage."""
        actor.money += GOVERNMENT_WAGE
        actor.last_action = f"Government work for {GOVERNMENT_WAGE} credits"
        return True


class CancelOrderCommand(MarketCommand):
    """Command to cancel a market order."""
    
    def __init__(self, order_id: str) -> None:
        self.order_id = order_id
    
    def execute(self, actor: 'Actor') -> bool:
        """Cancel a market order."""
        if not actor.planet:
            return False
        
        return actor.planet.market.cancel_order(self.order_id)


class PlaceBuyOrderCommand(MarketCommand):
    """Command to place a buy order on the market."""
    
    def __init__(self, commodity_type: 'CommodityDefinition', quantity: int, price: int) -> None:
        self.commodity_type = commodity_type
        self.quantity = quantity
        self.price = price
    
    def execute(self, actor: 'Actor') -> bool:
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
    
    def __init__(self, commodity_type: 'CommodityDefinition', quantity: int, price: int) -> None:
        self.commodity_type = commodity_type
        self.quantity = quantity
        self.price = price
    
    def execute(self, actor: 'Actor') -> bool:
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