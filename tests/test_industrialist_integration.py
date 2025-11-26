#!/usr/bin/env python3
"""Quick integration test for the Industrialist brain implementation."""

from spacesim2.core.simulation import Simulation

def test_industrialist_integration():
    """Test that we can create a simulation with Industrialists."""
    print("Creating simulation with Industrialists...")
    
    sim = Simulation()
    sim.setup_simple(num_planets=1, num_regular_actors=4, num_market_makers=1, num_ships=1)
    
    print(f"Created {len(sim.actors)} actors:")
    
    # Count actor types
    colonists = sum(1 for a in sim.actors if 'Colonist' in a.name)
    industrialists = sum(1 for a in sim.actors if 'Industrialist' in a.name)
    market_makers = sum(1 for a in sim.actors if 'MarketMaker' in a.name)
    
    for actor in sim.actors:
        brain_type = actor.brain.__class__.__name__
        print(f"  {actor.name}: {brain_type}")
    
    print(f"\nBreakdown:")
    print(f"  Colonists: {colonists}")
    print(f"  Industrialists: {industrialists}")
    print(f"  Market Makers: {market_makers}")
    
    # Test running a few turns
    print(f"\nRunning 3 turns...")
    for turn in range(3):
        print(f"Turn {turn + 1}")
        sim.run_turn()
        
        # Show what some actors did
        for actor in sim.actors[:3]:  # Show first 3 actors
            brain_type = actor.brain.__class__.__name__
            print(f"  {actor.name} ({brain_type}): {actor.last_action}")
    
    print("\nIntegration test completed successfully!")

if __name__ == "__main__":
    test_industrialist_integration()