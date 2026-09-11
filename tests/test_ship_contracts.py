"""Tests for the ship brain's side of contracts.

Riders on a trip the ship was making anyway, trips flown for contract
payments alone, the early consignment load that funds a broke ship's fuel,
the pin a loaded payload puts on the destination, and the reposition toward
a planet whose only export is a queue of jobs.
"""

from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.actor_brain import ActorBrain
from spacesim2.core.contracts import (
    GOVERNMENT,
    ConsignmentPayload,
    Contract,
    ContractStatus,
    PassengerPayload,
    load_contract,
)
from spacesim2.core.planet import Planet
from spacesim2.core.ship import ContractPlan, Ship, TradePlan
from tests.test_ship_fuel import _make_ship, _make_world


def _world(planet_specs, fuel_price=5, fuel_depth=200):
    """A galaxy with a deep fuel ask on every planet and contract counters."""
    sim, fuel, food, planets = _make_world(planet_specs)
    sim.actors = []
    sim.contracts_delivered = 0
    sim.contracts_stranded = 0
    sim.government_payouts = 0
    sim.migration_departures = 0
    sim.passage_wait_turns = []
    sim.migration_log = []
    for index, planet in enumerate(planets):
        supplier = _make_ship(
            sim, planet, hold_fuel=fuel_depth, name=f"Supplier{index}"
        )
        planet.market.place_sell_order(supplier, fuel, fuel_depth, fuel_price)
    return sim, fuel, food, planets


def _consignment(
    sim,
    origin: Planet,
    destination: Planet,
    advance: int = 200,
    on_delivery: int = 0,
    units: int = 20,
) -> Contract:
    """Post a government freight job and return it."""
    contract = Contract(
        poster=GOVERNMENT,
        origin=origin,
        destination=destination,
        payload=ConsignmentPayload(units=units),
        advance=advance,
        on_delivery=on_delivery,
        posted_turn=sim.current_turn,
        expires_turn=sim.current_turn + 50,
    )
    origin.contracts.post(contract)
    return contract


class _StayPutBrain(ActorBrain):
    """An actor brain that decides nothing."""

    def decide_economic_action(self, actor: Actor):
        return None

    def decide_market_actions(self, actor: Actor):
        return []


def _passenger(
    sim, origin: Planet, destination: Planet, advance: int = 200
) -> Contract:
    """Post a passage contract for a new actor living at ``origin``."""
    actor = Actor(
        name="Traveller",
        sim=sim,
        actor_type=ActorType.REGULAR,
        drives=[],
        brain=_StayPutBrain(),
        initial_money=1000,
    )
    sim.actors.append(actor)
    origin.add_actor(actor)
    contract = Contract(
        poster=actor,
        origin=origin,
        destination=destination,
        payload=PassengerPayload(actor=actor),
        advance=advance,
        on_delivery=0,
        posted_turn=sim.current_turn,
        expires_turn=sim.current_turn + 50,
    )
    origin.contracts.post(contract)
    return contract


def _loaded_plan(ship: Ship, origin: Planet, destination: Planet, food, quantity=10):
    """Put a haul aboard and mark its plan loaded, ready to depart."""
    ship.cargo.add_commodity(food, quantity)
    plan = TradePlan(
        origin=origin,
        destination=destination,
        commodity=food,
        quantity=quantity,
        bid_price_per_unit=10,
        purchase_price_per_unit=10,
        expected_sell_price_per_unit=30,
        distance=ship.route_distance(origin, destination),
        fuel_needed_one_way=ship.fuel_required(
            ship.route_distance(origin, destination)
        ),
        fuel_price_at_origin=5,
        fuel_units_from_tank=0,
        fuel_price_from_tank=5,
    )
    ship.brain._current_plan = plan
    ship.brain._plan_loaded = True
    return plan


# ---------------------------------------------------------------------------
# Riders
# ---------------------------------------------------------------------------


def test_riders_bound_elsewhere_are_left_on_the_board():
    """A departing ship takes the contracts to where it is going, and no others."""
    sim, _fuel, food, (a, b, c) = _world([("A", 0, 0), ("B", 50, 0), ("C", 0, 50)])
    ship = _make_ship(sim, a, fuel_units=40, money=2000, name="Trader")
    _loaded_plan(ship, a, b, food)

    wanted = _consignment(sim, a, b)
    unwanted = _consignment(sim, a, c)

    assert ship.brain.decide_travel() is b
    assert ship.contracts == [wanted]
    assert wanted.status is ContractStatus.ACCEPTED
    assert unwanted.status is ContractStatus.OPEN


def test_a_rider_loads_at_departure_and_is_delivered_on_arrival():
    """The payload boards when the journey starts and pays out on arrival."""
    sim, _fuel, food, (a, b) = _world([("A", 0, 0), ("B", 50, 0)])
    ship = _make_ship(sim, a, fuel_units=40, money=2000, name="Trader")
    _loaded_plan(ship, a, b, food)
    contract = _consignment(sim, a, b, advance=200, on_delivery=50)

    money_before = ship.money
    destination = ship.brain.decide_travel()
    assert destination is b
    assert ship.start_journey(destination)
    assert contract.status is ContractStatus.LOADED
    assert ship.money == money_before + 200

    while ship.destination is not None:
        ship.update_journey()

    assert contract.status is ContractStatus.DELIVERED
    assert ship.money == money_before + 250
    assert ship.contracts == []
    assert sim.contracts_delivered == 1


# ---------------------------------------------------------------------------
# Contract-only trips
# ---------------------------------------------------------------------------


def test_a_paying_job_is_taken_when_there_is_nothing_to_haul():
    """With no trade plan, a job that beats its fuel becomes the trip."""
    sim, _fuel, _food, (a, b) = _world([("A", 0, 0), ("B", 50, 0)])
    ship = _make_ship(sim, a, fuel_units=40, money=2000, name="Trader")
    contract = _consignment(sim, a, b, advance=300)

    ship.brain.decide_trade_actions()

    plan = ship.brain._current_plan
    assert isinstance(plan, ContractPlan)
    assert plan.destination is b
    assert plan.contracts == (contract,)
    assert contract.status is ContractStatus.ACCEPTED
    assert ship.brain.decide_travel() is b


def test_a_job_that_does_not_cover_its_fuel_is_refused():
    """Payments below the leg's fuel and maintenance are not worth flying."""
    sim, _fuel, _food, (a, b) = _world([("A", 0, 0), ("B", 50, 0)])
    ship = _make_ship(sim, a, fuel_units=40, money=2000, name="Trader")
    contract = _consignment(sim, a, b, advance=1)

    ship.brain.decide_trade_actions()

    assert ship.brain._current_plan is None
    assert ship.contracts == []
    assert contract.status is ContractStatus.OPEN


def test_a_broke_ship_funds_its_fuel_with_the_advance():
    """A dry, penniless ship loads the consignment early and buys fuel with it."""
    sim, fuel, _food, (a, b) = _world([("A", 0, 0), ("B", 50, 0)])
    ship = _make_ship(sim, a, fuel_units=0, money=0, name="Broke")
    contract = _consignment(sim, a, b, advance=400)

    ship.brain.decide_trade_actions()

    # The advance is in hand before the fuel bid goes in.
    assert contract.status is ContractStatus.LOADED
    assert ship.money + ship.reserved_money == 400
    assert any(order.actor is ship for order in a.market.buy_orders[fuel])

    for _ in range(6):
        a.market.match_orders()
        sim.current_turn += 1
        ship.take_turn()

    assert ship.departure_turns
    assert ship.planet is b
    assert contract.status is ContractStatus.DELIVERED


# ---------------------------------------------------------------------------
# Pinning
# ---------------------------------------------------------------------------


def test_a_loaded_passenger_pins_the_destination():
    """A payload aboard outranks the cargo the ship would rather chase."""
    sim, _fuel, food, (a, b, c) = _world([("A", 0, 0), ("B", 50, 0), ("C", 0, 50)])
    ship = _make_ship(sim, a, fuel_units=40, money=2000, name="Trader")
    # Cargo aboard that C pays well for: without the passenger the ship flies
    # there instead.
    ship.cargo.add_commodity(food, 10)
    buyer = _make_ship(sim, c, money=20000, name="BuyerC")
    c.market.place_buy_order(buyer, food, 10, 200)

    contract = _passenger(sim, a, b)
    assert a.contracts.accept(contract, ship)
    assert load_contract(ship, contract)

    ship.brain.decide_trade_actions()

    assert ship.brain._committed_fuel_need == ship.brain._departure_fuel_requirement(b)
    assert ship.brain.decide_travel() is b


# ---------------------------------------------------------------------------
# Remote pickup
# ---------------------------------------------------------------------------


def test_reposition_aims_at_a_planet_whose_only_export_is_jobs():
    """An empty ship with nothing to trade flies to where the jobs are."""
    sim, fuel, food, (a, b, c) = _world([("A", 0, 0), ("B", 50, 0), ("C", 0, 50)])
    # A galaxy-wide trade signal that backs no profitable plan: food is for
    # sale at C at a price no bid anywhere beats.
    seller = _make_ship(sim, c, name="SellerC")
    seller.cargo.add_commodity(food, 50)
    c.market.place_sell_order(seller, food, 50, 100)
    buyer = _make_ship(sim, c, money=5000, name="BuyerC")
    c.market.place_buy_order(buyer, food, 50, 5)

    ship = _make_ship(sim, a, fuel_units=40, money=2000, name="Trader")
    assert ship.brain._find_best_trade_plan() is None

    # Nothing at B to export, but a pile of freight bound for C.
    for _ in range(3):
        _consignment(sim, b, c, advance=300)

    assert ship.brain._find_reposition_target(ship.fuel, fuel) is b
