import pytest
import random
import math
from spacesim2.core.simulation import Simulation


class TestFictionalPlanets:
    """Test the fictional planet generation system."""

    def test_generates_correct_number_of_planets(self):
        """Test that the correct number of planets are generated."""
        sim = Simulation()
        sim.setup_simple(num_planets=5, num_regular_actors=1, num_market_makers=1, num_ships=1)
        
        assert len(sim.planets) == 5

    def test_planets_have_fictional_names(self):
        """Test that planets have fictional names, not Sol system names."""
        sim = Simulation()
        sim.setup_simple(num_planets=3, num_regular_actors=1, num_market_makers=1, num_ships=1)
        
        sol_system_names = {"Earth", "Mars", "Venus", "Jupiter", "Saturn", "Mercury", "Neptune", "Uranus"}
        planet_names = {planet.name for planet in sim.planets}
        
        # Should have no overlap with Sol system names
        assert len(planet_names.intersection(sol_system_names)) == 0

    def test_minimum_distance_separation(self):
        """Test that planets are at least 10 units apart."""
        random.seed(42)  # For reproducible test
        sim = Simulation()
        sim.setup_simple(num_planets=4, num_regular_actors=1, num_market_makers=1, num_ships=1)
        
        min_distance = float('inf')
        for i, planet1 in enumerate(sim.planets):
            for j, planet2 in enumerate(sim.planets):
                if i < j:  # Only check each pair once
                    distance = math.sqrt((planet1.x - planet2.x)**2 + (planet1.y - planet2.y)**2)
                    min_distance = min(min_distance, distance)
        
        assert min_distance >= 10.0, f"Minimum distance {min_distance} is less than 10.0"

    def test_planets_within_map_bounds(self):
        """Test that all planets are within reasonable map bounds."""
        sim = Simulation()
        sim.setup_simple(num_planets=6, num_regular_actors=1, num_market_makers=1, num_ships=1)
        
        for planet in sim.planets:
            assert 0 <= planet.x <= 100, f"Planet {planet.name} x-coordinate {planet.x} out of bounds"
            assert 0 <= planet.y <= 100, f"Planet {planet.name} y-coordinate {planet.y} out of bounds"

    def test_unique_planet_names(self):
        """Test that all planet names are unique."""
        sim = Simulation()
        sim.setup_simple(num_planets=8, num_regular_actors=1, num_market_makers=1, num_ships=1)
        
        planet_names = [planet.name for planet in sim.planets]
        assert len(planet_names) == len(set(planet_names)), "Duplicate planet names found"

    def test_position_generation_with_limited_space(self):
        """Test that position generation handles cases where space is limited."""
        # Test with many planets in small space - should still work but may generate fewer
        sim = Simulation()
        
        # This should work but may generate fewer planets than requested if space is too constrained
        sim.setup_simple(num_planets=20, num_regular_actors=1, num_market_makers=1, num_ships=1)
        
        # Should generate at least some planets
        assert len(sim.planets) > 0
        
        # If multiple planets generated, check minimum distance
        if len(sim.planets) > 1:
            min_distance = float('inf')
            for i, planet1 in enumerate(sim.planets):
                for j, planet2 in enumerate(sim.planets):
                    if i < j:
                        distance = math.sqrt((planet1.x - planet2.x)**2 + (planet1.y - planet2.y)**2)
                        min_distance = min(min_distance, distance)
            
            assert min_distance >= 10.0