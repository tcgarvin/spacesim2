import random
from typing import Optional, Dict, List, Union, Tuple, Any, TYPE_CHECKING
import enum

from spacesim2.core.planet import Planet
from spacesim2.core.commodity import Inventory

if TYPE_CHECKING:
    from spacesim2.core.actor_brain import ActorBrain
    from spacesim2.core.simulation import Simulation
    from spacesim2.core.drives.actor_drive import ActorDrive


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
        actor_type: ActorType,
        drives: List['ActorDrive'],
        brain: 'ActorBrain',
        planet: Optional[Planet] = None,
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
        self.drives = drives  # List of ActorDrive instances
        
        # Initialize skills
        self.skills: Dict[str, float] = {}
        
        # Apply any initial skills provided
        if initial_skills:
            for skill_id, rating in initial_skills.items():
                self.skills[skill_id] = rating
        
        self.brain = brain
        self.last_market_check_turn: int = 0  # Track when actor last checked market status
    
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
        # Step 2: Perform economic action
        economic_command = self.brain.decide_economic_action(self)
        if economic_command:
            economic_command.execute(self)
            self.sim.data_logger.log_actor_command(self, economic_command)
        
        # Step 3: Perform market actions
        market_commands = self.brain.decide_market_actions(self)
        market_actions = []
        for command in market_commands:
            success = command.execute(self)
            # Log all market commands to data logger
            self.sim.data_logger.log_actor_command(self, command)
            # Only log buy/sell order commands for market action summary
            if success and ('Buy' in command.__class__.__name__ or 'Sell' in command.__class__.__name__):
                action_type = "Buy" if "Buy" in command.__class__.__name__ else "Sell"
                commodity_name = command.commodity_type.id
                market_actions.append(f"{action_type} {command.quantity} {commodity_name} at {command.price}")
        
        # Update the actor's last market action summary
        if market_actions:
            self.last_market_action = "; ".join(market_actions)
        else:
            self.last_market_action = "No market actions"

        for drive in self.drives:
            drive.tick(self)

        self.sim.data_logger.log_actor_metrics(self)
        self.sim.data_logger.log_actor_inventory(self)
        self.sim.data_logger.log_actor_market_status(self)

    def can_execute_process(self, process_id: str) -> bool:
        """Check if actor can execute a process without actually executing it."""
        # Actor always has sim reference
            
        process = self.sim.process_registry.get_process(process_id)
        if not process:
            return False
            
        # Check if actor has required inputs
        for commodity, quantity in process.inputs.items():
            if not self.inventory.has_quantity(commodity, quantity):
                return False
                
        # Check if actor has required tools
        for tool in process.tools_required:
            if not self.inventory.has_quantity(tool, 1):
                return False
                
        # Check if actor has access to required facilities in their inventory
        for facility in process.facilities_required:
            if not self.inventory.has_quantity(facility, 1):
                return False
        
        return True
    

    def get_market_activity_since_last_check(self) -> Dict:
        """Actor decides what's relevant - since they last checked."""
        if not self.planet:
            return {}
        
        market = self.planet.market
        current_orders = market.get_actor_current_orders(self)
        events = market.get_actor_order_events(self, since_turn=self.last_market_check_turn)
        transactions = market.get_actor_transactions_range(self, since_turn=self.last_market_check_turn)
        
        # Update context
        self.last_market_check_turn = self.sim.current_turn
        
        return {
            "current_orders": current_orders,
            "events_since_last_check": events,
            "transactions_since_last_check": transactions
        }
    
    def get_market_activity_this_turn(self) -> Dict:
        """Actor decides: just this turn's activity."""
        if not self.planet:
            return {}
        
        market = self.planet.market
        return {
            "current_orders": market.get_actor_current_orders(self),
            "events_this_turn": market.get_actor_order_events(self, since_turn=self.sim.current_turn),
            "transactions_this_turn": market.get_actor_transactions_range(self, since_turn=self.sim.current_turn)
        }
    
    def get_market_activity_last_n_turns(self, n: int) -> Dict:
        """Actor decides: last N turns."""
        if not self.planet:
            return {}
        
        market = self.planet.market
        since_turn = max(0, self.sim.current_turn - n)
        return {
            "current_orders": market.get_actor_current_orders(self),
            "events_last_n_turns": market.get_actor_order_events(self, since_turn=since_turn),
            "transactions_last_n_turns": market.get_actor_transactions_range(self, since_turn=since_turn)
        }

    def __repr__(self):
        return f"Actor(name={self.name})"