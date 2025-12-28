import pytest

from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.brains.colonist import ColonistBrain
from spacesim2.core.brains import MarketMakerBrain
from spacesim2.core.market import Market
from spacesim2.core.planet import Planet

from .helpers import get_actor


def test_actor_initialization(mock_sim, mock_brain) -> None:
    """Test that an actor can be initialized correctly."""
    actor = Actor("Test Actor", mock_sim, ActorType.REGULAR, [], mock_brain, initial_money=50)
    assert actor.name == "Test Actor"
    assert actor.money == 50
    assert actor.inventory is not None
    assert actor.actor_type == ActorType.REGULAR
    

def test_actor_government_work() -> None:
    """Test that an actor earns money from government work."""
    actor = get_actor(initial_money=0)
    
    # Test via command pattern
    from spacesim2.core.commands import GovernmentWorkCommand
    command = GovernmentWorkCommand()
    command.execute(actor)
    
    assert actor.money == 10  # Government wage