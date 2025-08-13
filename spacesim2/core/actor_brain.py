from typing import Optional, List, TYPE_CHECKING

from spacesim2.core.commands import EconomicCommand, MarketCommand

if TYPE_CHECKING:
    from spacesim2.core.actor import Actor


class ActorBrain:
    """Base class for actor decision making strategies."""
    
    def decide_economic_action(self, actor:'Actor') -> Optional[EconomicCommand]:
        """Decide which economic action to take this turn."""
        raise NotImplementedError("Subclasses must implement this method")
    
    def decide_market_actions(self, actor:'Actor') -> List[MarketCommand]:
        """Decide what market actions to take this turn."""
        raise NotImplementedError("Subclasses must implement this method")