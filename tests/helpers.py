import random

from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.commands import GovernmentWorkCommand
from spacesim2.core.commodity import CommodityRegistry


class FixedRandom(random.Random):
    """A `random.Random` whose `random()` always returns a fixed value.

    Used to pin per-actor RNG outcomes (tool breakage, drive events, skill
    rolls) deterministically: assign it to `actor.rng`.
    """

    def __init__(self, value: float) -> None:
        super().__init__()
        self._value = value

    def random(self) -> float:
        return self._value


def _get_mock_sim():
    return type(
        "MockSimulation", (object,), {"commodity_registry": CommodityRegistry()}
    )()


def _get_mock_brain():
    return type(
        "MockBrain",
        (object,),
        {
            "decide_economic_action": lambda _: GovernmentWorkCommand(),
            "decide_market_actions": lambda _: [],
        },
    )


def get_actor(
    name="DefaultTestActor",
    sim=None,
    actor_type=ActorType.REGULAR,
    brain=None,
    planet=None,
    initial_money=50,
    initial_skills={},
) -> Actor:
    if sim is None:
        sim = _get_mock_sim()

    if brain is None:
        brain = _get_mock_brain()

    return Actor(
        name,
        sim,
        actor_type,
        [],  # drives
        brain,
        planet,
        initial_money,
        initial_skills,
    )
