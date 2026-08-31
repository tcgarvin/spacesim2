"""Tests for large-galaxy setup: name generation, position sampling, map scaling."""

import math

import pytest

from spacesim2.core.simulation import (
    BASE_MAP_SIZE,
    MIN_PLANET_DISTANCE,
    Simulation,
)


def _min_pairwise_distance(positions: list[tuple[float, float]]) -> float:
    """Return the smallest pairwise distance among positions."""
    best = math.inf
    for i, (x1, y1) in enumerate(positions):
        for x2, y2 in positions[i + 1 :]:
            best = min(best, math.hypot(x1 - x2, y1 - y2))
    return best


def test_500_planet_setup_produces_exactly_500_planets() -> None:
    """A 500-planet galaxy must have 500 planets, unique names, valid spacing."""
    sim = Simulation()
    sim.setup_simple(
        num_planets=500,
        num_regular_actors=0,
        num_market_makers=0,
        num_ships=0,
    )

    assert len(sim.planets) == 500

    names = [p.name for p in sim.planets]
    assert len(set(names)) == 500, "planet names must be unique"
    assert all(name for name in names), "planet names must be non-empty"

    positions = [(p.x, p.y) for p in sim.planets]
    # Grid boundaries can produce distances of exactly min_distance; allow
    # a tiny epsilon for float error.
    assert _min_pairwise_distance(positions) >= MIN_PLANET_DISTANCE - 1e-9


def test_small_galaxy_keeps_current_spatial_scale() -> None:
    """A 5-planet galaxy stays on roughly the historical 100x100 map."""
    sim = Simulation()
    sim.setup_simple(
        num_planets=5,
        num_regular_actors=0,
        num_market_makers=0,
        num_ships=0,
    )

    assert len(sim.planets) == 5
    positions = [(p.x, p.y) for p in sim.planets]
    for x, y in positions:
        assert 0.0 <= x <= BASE_MAP_SIZE
        assert 0.0 <= y <= BASE_MAP_SIZE
    assert _min_pairwise_distance(positions) >= MIN_PLANET_DISTANCE - 1e-9


def test_positions_raise_when_map_cannot_fit_request() -> None:
    """The sampler fails loudly rather than returning fewer positions."""
    sim = Simulation()
    with pytest.raises(ValueError):
        sim._generate_separated_positions(
            num_positions=500, min_distance=10.0, map_size=100.0
        )


def test_procedural_names_are_unique_and_readable() -> None:
    """The procedural name generator avoids collisions with used names."""
    used: set[str] = set()
    for _ in range(1000):
        name = Simulation._generate_procedural_name(used)
        assert name not in used
        assert name[0].isupper()
        used.add(name)


def test_map_scales_with_planet_count() -> None:
    """Bigger galaxies get bigger maps (constant density), spacing preserved."""
    sim = Simulation()
    planet_data = sim._generate_fictional_planets(200)

    assert len(planet_data) == 200
    max_coord = max(max(x, y) for _, x, y in planet_data)
    # Density rule: map side = sqrt(2000 * n) for n=200 -> ~632.
    assert max_coord > BASE_MAP_SIZE, "200-planet map should exceed the base map"
    positions = [(x, y) for _, x, y in planet_data]
    assert _min_pairwise_distance(positions) >= MIN_PLANET_DISTANCE - 1e-9
