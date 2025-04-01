#!/usr/bin/env python
"""
Simple script to test the commodity and process system in the simulation.
"""

from spacesim2.core.simulation import Simulation

def main():
    """Run a simple simulation with the new commodity and process system."""
    sim = Simulation()
    sim.setup_simple(num_regular_actors=2, num_market_makers=1, num_ships=1)
    print("\nStarting simulation with commodity and process system...")
    sim.run_simulation(5)
    print("\nSimulation complete!")

if __name__ == "__main__":
    main()