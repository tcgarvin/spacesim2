from spacesim2.core.simulation import Simulation
from spacesim2.core.skill import SkillCheck

def test_skill_system():
    """Test the skill-based process execution system."""
    # Initialize simulation
    sim = Simulation()
    
    # Set up simple simulation
    sim.setup_simple(num_regular_actors=8, num_market_makers=1)
    
    # Print actor skills
    print("\n=== Actor Skills ===")
    for actor in sim.actors:
        print(f"Actor: {actor.name}")
        
        # Print all skills
        for skill_id, rating in actor.skills.items():
            print(f"  - {skill_id}: {rating:.2f}")
        
        # Calculate success and multiplier chances for a few example skills
        mining_rating = actor.get_skill_rating('mining')
        refining_rating = actor.get_skill_rating('refining')
        
        # Calculate probabilities
        mining_success = "100%" if mining_rating >= 1.0 else f"{mining_rating*100:.1f}%"
        mining_multiplier = "0%" if mining_rating <= 1.0 else f"{(mining_rating-1.0)*50:.1f}%"
        
        refining_success = "100%" if refining_rating >= 1.0 else f"{refining_rating*100:.1f}%"
        refining_multiplier = "0%" if refining_rating <= 1.0 else f"{(refining_rating-1.0)*50:.1f}%"
        
        print(f"  Mining: Success {mining_success}, Multiplier {mining_multiplier}")
        print(f"  Refining: Success {refining_success}, Multiplier {refining_multiplier}")
        print("")
    
    # Run a few turns to see how skills affect process execution
    for _ in range(5):
        sim.run_turn()

if __name__ == "__main__":
    test_skill_system()