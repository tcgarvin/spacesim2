"""Prosperity drives: gate, taste scaling, consumption, and brain wiring."""

from pathlib import Path
from unittest.mock import patch

import pytest

from spacesim2.core.actor import ActorType
from spacesim2.core.commodity import CommodityRegistry
from spacesim2.core.drives import ClothingDrive, FoodDrive, HealthDrive, ShelterDrive
from spacesim2.core.drives.prosperity_drive import (
    CATEGORY_NAMES,
    DEBT_DECAY_FACTOR,
    DEBT_MISS_PENALTY,
    GATE_MAX_DEBT,
    GATE_MIN_BUFFER,
    PROSPERITY_CATEGORIES,
    TASTE_BASE,
    TASTE_FAVORITE,
    ProsperityDrive,
    ProsperityDriveMetrics,
    needs_are_met,
    prosperity_drives,
    prosperity_index,
    random_tastes,
)
from spacesim2.core.simulation import Simulation
from tests.helpers import get_actor

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def registry() -> CommodityRegistry:
    reg = CommodityRegistry()
    reg.load_from_file(DATA_DIR / "commodities.yaml")
    return reg


def _category(name: str):
    return next(c for c in PROSPERITY_CATEGORIES if c.name == name)


def _actor_with_needs(registry: CommodityRegistry, tastes=None):
    actor = get_actor("Prosperous")
    actor.drives = [
        Drive(registry)
        for Drive in (FoodDrive, ClothingDrive, ShelterDrive, HealthDrive)
    ]
    actor.drives.extend(prosperity_drives(registry, tastes or {}))
    return actor


def _satisfy_needs(actor) -> None:
    for drive in actor.drives:
        if drive.WELLBEING:
            drive.metrics.debt = 0.0
            drive.metrics.buffer = 1.0


class TestTastes:
    def test_random_tastes_has_one_favorite(self):
        """Every category is weighted, exactly one at the favorite weight."""
        tastes = random_tastes()
        assert set(tastes) == set(CATEGORY_NAMES)
        assert sorted(tastes.values())[:-1] == [TASTE_BASE] * (len(CATEGORY_NAMES) - 1)
        assert max(tastes.values()) == TASTE_FAVORITE

    def test_taste_scales_rate_and_target(self, registry):
        """The favorite good is used faster and stocked deeper."""
        cat = _category("clothing")
        plain = ProsperityDrive(registry, cat, TASTE_BASE)
        keen = ProsperityDrive(registry, cat, TASTE_FAVORITE)
        assert keen.event_prob == pytest.approx(plain.event_prob * TASTE_FAVORITE)
        assert keen.target_units() == plain.target_units() * TASTE_FAVORITE

    def test_taste_does_not_change_penalty(self, registry):
        """Preference works through the buffer, never through the stake."""
        cat = _category("luxury")
        assert (
            ProsperityDrive(registry, cat, TASTE_FAVORITE).deprivation_stake()
            == ProsperityDrive(registry, cat, TASTE_BASE).deprivation_stake()
        )

    def test_non_positive_taste_rejected(self, registry):
        """A zero taste is a configuration error, not a silent no-op."""
        with pytest.raises(ValueError):
            ProsperityDrive(registry, _category("food"), 0.0)


class TestGate:
    def test_needs_met_when_all_needs_healthy(self, registry):
        """Low debt and adequate buffer on every need opens the gate."""
        actor = _actor_with_needs(registry)
        _satisfy_needs(actor)
        assert needs_are_met(actor)
        assert all(d.can_purchase(actor) for d in actor.drives)

    def test_one_indebted_need_closes_gate(self, registry):
        """A single need at the debt threshold blocks every prosperity bid."""
        actor = _actor_with_needs(registry)
        _satisfy_needs(actor)
        actor.drives[2].metrics.debt = GATE_MAX_DEBT
        assert not needs_are_met(actor)
        assert not any(d.can_purchase(actor) for d in actor.drives if not d.WELLBEING)

    def test_thin_buffer_closes_gate(self, registry):
        """A need below the buffer floor blocks prosperity bids."""
        actor = _actor_with_needs(registry)
        _satisfy_needs(actor)
        actor.drives[0].metrics.buffer = GATE_MIN_BUFFER - 0.01
        assert not needs_are_met(actor)

    def test_need_drives_always_may_purchase(self, registry):
        """The gate never applies to needs themselves."""
        actor = _actor_with_needs(registry)
        for drive in actor.drives:
            drive.metrics.debt = 1.0
        assert all(d.can_purchase(actor) for d in actor.drives if d.WELLBEING)

    def test_full_food_pantry_passes_buffer_floor(self, registry):
        """An actor holding the food target passes the gate on food."""
        actor = _actor_with_needs(registry)
        food = actor.drives[0]
        actor.inventory.add_commodity(food.food_commodity, food.target_units())
        food.tick(actor)
        assert food.metrics.buffer >= GATE_MIN_BUFFER


class TestTick:
    def test_not_a_need(self, registry):
        """Prosperity drives are excluded from wellbeing."""
        drive = ProsperityDrive(registry, _category("food"))
        assert drive.WELLBEING is False
        assert drive.metrics.get_name() == "prosperity_food"

    @patch("spacesim2.core.drives.prosperity_drive.random.random", return_value=0.0)
    def test_served_event_consumes_and_raises_coverage(self, _rand, registry):
        """An event with stock removes one unit and moves coverage toward 1."""
        drive = ProsperityDrive(registry, _category("luxury"))
        actor = get_actor("Rich")
        actor.inventory.add_commodity(drive.good, 2)
        metrics = drive.tick(actor)
        assert isinstance(metrics, ProsperityDriveMetrics)
        assert actor.inventory.get_available_quantity(drive.good) == 1
        assert metrics.health == 1.0
        assert metrics.debt == 0.0
        assert 0.0 < metrics.coverage < 1.0

    @patch("spacesim2.core.drives.prosperity_drive.random.random", return_value=0.0)
    def test_missed_event_adds_debt_and_lowers_coverage(self, _rand, registry):
        """An event with no stock adds the miss penalty and decays coverage."""
        drive = ProsperityDrive(registry, _category("computing"))
        drive.metrics.coverage = 1.0
        drive.metrics.debt = 0.5
        actor = get_actor("Poor")
        metrics = drive.tick(actor)
        assert metrics.health == 0.0
        assert metrics.debt == pytest.approx(
            0.5 * DEBT_DECAY_FACTOR + DEBT_MISS_PENALTY
        )
        assert metrics.coverage < 1.0

    @patch("spacesim2.core.drives.prosperity_drive.random.random", return_value=1.0)
    def test_quiet_turn_holds_debt_and_coverage(self, _rand, registry):
        """Between events nothing is consumed and the EMA does not move."""
        drive = ProsperityDrive(registry, _category("shelter"))
        drive.metrics.coverage = 0.4
        drive.metrics.debt = 0.2
        actor = get_actor("Waiting")
        actor.inventory.add_commodity(drive.good, 1)
        metrics = drive.tick(actor)
        assert actor.inventory.get_available_quantity(drive.good) == 1
        assert metrics.coverage == 0.4
        assert metrics.debt == 0.2
        assert metrics.buffer > 0.0

    @patch("spacesim2.core.drives.prosperity_drive.random.random", return_value=1.0)
    def test_taste_cancels_in_buffer(self, _rand, registry):
        """Target stock at any taste gives the same buffer reading."""
        cat = _category("clothing")
        readings = []
        for taste in (TASTE_BASE, TASTE_FAVORITE):
            drive = ProsperityDrive(registry, cat, taste)
            actor = get_actor("Any")
            actor.inventory.add_commodity(drive.good, drive.target_units())
            readings.append(drive.tick(actor).buffer)
        assert readings[0] == pytest.approx(readings[1])


class TestIndex:
    def test_index_is_mean_coverage(self, registry):
        """The index averages coverage over prosperity drives only."""
        actor = _actor_with_needs(registry)
        prosperous = [d for d in actor.drives if not d.WELLBEING]
        for i, drive in enumerate(prosperous):
            assert isinstance(drive.metrics, ProsperityDriveMetrics)
            drive.metrics.coverage = 1.0 if i < 3 else 0.0
        assert prosperity_index(actor) == pytest.approx(0.5)

    def test_index_zero_without_prosperity_drives(self, registry):
        actor = get_actor("Plain")
        assert prosperity_index(actor) == 0.0


class TestBrainWiring:
    @pytest.fixture(scope="class")
    def sim(self) -> Simulation:
        sim = Simulation()
        sim.setup_simple(
            num_planets=1, num_regular_actors=4, num_market_makers=1, num_ships=0
        )
        return sim

    def _regular(self, sim: Simulation):
        return next(a for a in sim.actors if a.actor_type == ActorType.REGULAR)

    def test_setup_attaches_tastes_and_prosperity_drives(self, sim):
        """Every regular actor gets a taste vector and one drive per category."""
        actor = self._regular(sim)
        assert set(actor.tastes) == set(CATEGORY_NAMES)
        names = [d.metrics.get_name() for d in actor.drives]
        assert names[:4] == ["food", "clothing", "shelter", "health"]
        assert names[4:] == [f"prosperity_{c}" for c in CATEGORY_NAMES]

    def test_priority_puts_prosperity_last(self, sim):
        """Prosperity drives sort behind every need regardless of welfare."""
        actor = self._regular(sim)
        for drive in actor.drives:
            drive.metrics.buffer = 1.0 if drive.WELLBEING else 0.0
        ordered = actor.brain._drives_by_priority(actor)
        assert ordered[0].metrics.get_name() == "food"
        flags = [d.WELLBEING for d in ordered]
        assert flags == sorted(flags, reverse=True)

    def test_gate_blocks_prosperity_bids(self, sim):
        """With a need in debt, no buy order names a prosperity good."""
        actor = self._regular(sim)
        actor.money = 10_000
        _satisfy_needs(actor)
        actor.drives[1].metrics.debt = 0.9
        prosperity_ids = {c.commodity_id for c in PROSPERITY_CATEGORIES}
        commands = actor.brain._drive_buy_commands(actor, actor.planet.market)
        assert not any(c.commodity_type.id in prosperity_ids for c in commands)

    def test_met_needs_unlock_prosperity_bids(self, sim):
        """A rich actor with met needs bids for at least one prosperity good."""
        actor = self._regular(sim)
        actor.money = 10_000
        _satisfy_needs(actor)
        for drive in actor.drives:
            if drive.WELLBEING:
                for material in drive.materials():
                    actor.inventory.add_commodity(material, drive.target_units())
        prosperity_ids = {c.commodity_id for c in PROSPERITY_CATEGORIES}
        commands = actor.brain._drive_buy_commands(actor, actor.planet.market)
        assert any(c.commodity_type.id in prosperity_ids for c in commands)
