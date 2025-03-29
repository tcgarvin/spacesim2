import random
from typing import List, Dict, Optional

from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.commodity import CommodityType
from spacesim2.core.market import Market
from spacesim2.core.planet import Planet


class Simulation:
    """Main simulation controller."""

    def __init__(self) -> None:
        self.planets: List[Planet] = []
        self.actors: List[Actor] = []
        self.current_turn = 0
        self.market_stats: Dict = {}  # Track market statistics

    def setup_simple(self, num_regular_actors: int = 4, num_market_makers: int = 1) -> None:
        """Set up a simple simulation with one planet and multiple actors.

        Args:
            num_regular_actors: Number of regular actors to create
            num_market_makers: Number of market makers to create
        """
        # Create a planet
        planet = Planet("Earth")
        self.planets.append(planet)
        
        # Create and initialize the market for the planet
        market = Market()
        planet.market = market
        
        # Create regular actors with varying production efficiencies
        for i in range(1, num_regular_actors + 1):
            # Random production efficiency between 0.7 and 1.3
            efficiency = random.uniform(0.7, 1.3)
            
            actor = Actor(
                name=f"Colonist-{i}", 
                planet=planet,
                actor_type=ActorType.REGULAR,
                production_efficiency=efficiency,
                initial_money=50.0
            )
            self.actors.append(actor)
            planet.add_actor(actor)

        # Create market makers
        for i in range(1, num_market_makers + 1):
            actor = Actor(
                name=f"MarketMaker-{i}", 
                planet=planet,
                actor_type=ActorType.MARKET_MAKER,
                initial_money=200.0
            )
            self.actors.append(actor)
            planet.add_actor(actor)
            
        # Give some initial food to market makers to jumpstart the market
        for actor in self.actors:
            if actor.actor_type == ActorType.MARKET_MAKER:
                actor.inventory.add_commodity(CommodityType.RAW_FOOD, 20)
                
        # Give regular actors some food to get started
        for actor in self.actors:
            if actor.actor_type == ActorType.REGULAR:
                actor.inventory.add_commodity(CommodityType.RAW_FOOD, 3)

    def run_turn(self) -> None:
        """Run a single turn of the simulation."""
        self.current_turn += 1
        print(f"\n=== Turn {self.current_turn} ===")

        # Update market turn counters
        for planet in self.planets:
            if planet.market:
                planet.market.set_current_turn(self.current_turn)

        # Randomize actor order
        random.shuffle(self.actors)

        # Each actor takes their turn
        for actor in self.actors:
            actor.take_turn()
            
        # Process markets
        self._process_markets()

        # Print status after the turn
        self._print_status()
        
    def _process_markets(self) -> None:
        """Process all markets at the end of the turn."""
        for planet in self.planets:
            if planet.market:
                # Execute trades
                planet.market.match_orders()
                
                # Record market statistics
                self._record_market_stats(planet)
                
                # Clear orders at the end of the turn
                planet.market.clear_orders()

    def _record_market_stats(self, planet: Planet) -> None:
        """Record market statistics for analysis."""
        if not planet.market:
            return
            
        market = planet.market
        
        # Get average price for raw food
        avg_price = market.get_avg_price(CommodityType.RAW_FOOD)
        
        # Count transactions
        food_transactions = sum(
            1 for t in market.transaction_history 
            if t.commodity_type == CommodityType.RAW_FOOD
        )
        
        # Calculate trading volume
        food_volume = sum(
            t.quantity for t in market.transaction_history 
            if t.commodity_type == CommodityType.RAW_FOOD
        )
        
        # Store stats
        if planet.name not in self.market_stats:
            self.market_stats[planet.name] = {
                "food_prices": [],
                "food_transactions": [],
                "food_volume": []
            }
            
        self.market_stats[planet.name]["food_prices"].append(avg_price)
        self.market_stats[planet.name]["food_transactions"].append(food_transactions)
        self.market_stats[planet.name]["food_volume"].append(food_volume)

    def run_simulation(self, num_turns: int) -> None:
        """Run the simulation for a specified number of turns."""
        for _ in range(num_turns):
            self.run_turn()

    def _print_status(self) -> None:
        """Print the current status of the simulation."""
        for planet in self.planets:
            print(f"Planet: {planet.name}")
            
            # Calculate market statistics if available
            if planet.market:
                food_price = planet.market.get_avg_price(CommodityType.RAW_FOOD)
                print(f"  Market: Raw Food Price: {food_price}")
                
                # Print transactions
                if planet.market.transaction_history:
                    latest_transactions = planet.market.transaction_history[-min(3, len(planet.market.transaction_history)):]
                    print(f"  Recent Transactions:")
                    for tx in latest_transactions:
                        print(f"    {tx.buyer.name} bought {tx.quantity} {tx.commodity_type.name} from {tx.seller.name} @ {tx.price}")
                else:
                    print("  No transactions yet")
            
            # Print actor status
            for actor in planet.actors:
                food_qty = actor.inventory.get_quantity(CommodityType.RAW_FOOD)
                food_status = "✓" if actor.food_consumed_this_turn else "✗"
                
                # Show market maker status differently
                if actor.actor_type == ActorType.MARKET_MAKER:
                    print(f"  [MM] {actor.name}: {actor.money} credits, {food_qty} food {food_status}")
                else:
                    print(f"  {actor.name}: {actor.money} credits, {food_qty} food {food_status}")
                
            # Count hunger
            hungry_count = sum(1 for a in planet.actors if not a.food_consumed_this_turn)
            if hungry_count > 0:
                print(f"  {hungry_count} actors couldn't eat this turn!")