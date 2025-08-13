import random
from typing import Optional, Dict, List, Union, Tuple, Any, TYPE_CHECKING
import enum

from spacesim2.core.planet import Planet
from spacesim2.core.commodity import Inventory, CommodityDefinition
from spacesim2.core.actor_brain import ActorBrain, ColonistBrain, MarketMakerBrain

if TYPE_CHECKING:
    from spacesim2.core.simulation import Simulation
    from spacesim2.core.process import ProcessDefinition
    from spacesim2.core.skill import Skill


class ActorType(enum.Enum):
    """Types of actors in the simulation."""
    
    REGULAR = "regular"
    MARKET_MAKER = "market_maker"


class Actor:
    """Represents an economic actor in the simulation."""

    def __init__(
        self, 
        name: str, 
        sim: 'Simulation',
        planet: Optional[Planet] = None,
        actor_type: ActorType = ActorType.REGULAR,
        initial_money: int = 50,
        initial_skills: Optional[Dict[str, float]] = None
    ) -> None:
        self.name = name
        # Market makers get more initial money
        if actor_type == ActorType.MARKET_MAKER and initial_money == 50:
            self.money = 200
        else:
            self.money = initial_money
        self.reserved_money = 0  # Money reserved for market orders
        self.planet = planet
        self.inventory = Inventory()
        self.actor_type = actor_type
        self.market_history: List[Dict] = []  # Track this actor's market activity
        self.active_orders: Dict[str, str] = {}  # Track active order IDs and their types
        self.food_consumed_this_turn = False  # Track if actor has consumed food this turn
        self.last_action = "None"  # Track the last action performed
        self.last_market_action = "None"  # Track the last market action
        self.sim = sim  # Reference to the simulation
        
        # Initialize skills
        self.skills: Dict[str, float] = {}
        
        # Apply any initial skills provided
        if initial_skills:
            for skill_id, rating in initial_skills.items():
                self.skills[skill_id] = rating
        
        # Give actor a brain based on type
        if actor_type == ActorType.MARKET_MAKER:
            self.brain = MarketMakerBrain(self)
        else:
            self.brain = ColonistBrain(self)
    
    def get_skill_rating(self, skill_id: str) -> float:
        """Get the actor's rating for a specific skill.
        
        Args:
            skill_id: The ID of the skill to check
            
        Returns:
            The actor's rating for the skill, defaulting to 0.5 if not found
        """
        return self.skills.get(skill_id, 0.5)
    
    def set_skill_rating(self, skill_id: str, rating: float) -> None:
        """Set the actor's rating for a specific skill.
        
        Args:
            skill_id: The ID of the skill to set
            rating: The new rating for the skill
        """
        self.skills[skill_id] = max(0.5, min(3.0, rating))  # Clamp between 0.5 and 3.0
    
    def improve_skill(self, skill_id: str, amount: float) -> None:
        """Improve the actor's rating for a specific skill.
        
        Args:
            skill_id: The ID of the skill to improve
            amount: The amount to increase the skill rating by
        """
        current_rating = self.get_skill_rating(skill_id)
        self.set_skill_rating(skill_id, current_rating + amount)

    def take_turn(self) -> None:
        """Perform actions for this turn.

        Each turn consists of:
        1. Consume food
        2. One economic action (e.g., government work, production)
        3. Optional market actions
        """
        # Step 1: Consume food if available
        self._consume_food()
        
        # Step 2: Perform economic action
        economic_command = self.brain.decide_economic_action()
        if economic_command:
            economic_command.execute(self)
        
        # Step 3: Perform market actions
        market_commands = self.brain.decide_market_actions()
        market_actions = []
        for command in market_commands:
            success = command.execute(self)
            # Only log buy/sell order commands
            if success and ('Buy' in command.__class__.__name__ or 'Sell' in command.__class__.__name__):
                action_type = "Buy" if "Buy" in command.__class__.__name__ else "Sell"
                commodity_name = command.commodity_type.id
                market_actions.append(f"{action_type} {command.quantity} {commodity_name} at {command.price}")
        
        # Update the actor's last market action summary
        if market_actions:
            self.last_market_action = "; ".join(market_actions)
        else:
            self.last_market_action = "No market actions"

    def _consume_food(self) -> None:
        """Consume 1 unit of food per turn if available."""
        # Check if the actor has food in inventory
        # Get commodity references - sim must be set before calling this
        food_commodity = self.sim.commodity_registry.get_commodity("food")
        if not food_commodity:
            self.food_consumed_this_turn = False
            return
            
        # Try to consume from available food
        if self.inventory.has_quantity(food_commodity, 1):
            self.inventory.remove_commodity(food_commodity, 1)
            self.food_consumed_this_turn = True
            return
        
        # Check if there's reserved food
        reserved_food = self.inventory.get_reserved_quantity(food_commodity)
        if reserved_food > 0:
            # Unreserve 1 unit of food and consume it
            self.inventory.unreserve_commodity(food_commodity, 1)
            
            # Now the food should be available to consume
            if self.inventory.has_quantity(food_commodity, 1):
                self.inventory.remove_commodity(food_commodity, 1)
                self.food_consumed_this_turn = True
                return
        
        # If we get here, there's not enough food
        self.food_consumed_this_turn = False