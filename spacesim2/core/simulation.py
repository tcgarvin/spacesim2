import random
import os
from typing import List, Dict, Optional

from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.commodity import CommodityRegistry
from spacesim2.core.process import ProcessRegistry
from spacesim2.core.market import Market
from spacesim2.core.planet import Planet
from spacesim2.core.ship import Ship, ShipStatus
from spacesim2.core.skill import SkillsRegistry


class Simulation:
    """Main simulation controller."""
    
    # Class variable to store the global instance
    instance = None

    def __init__(self) -> None:
        self.planets: List[Planet] = []
        self.actors: List[Actor] = []
        self.ships: List[Ship] = []
        self.current_turn = 0
        self.market_stats: Dict = {}  # Track market statistics
        
        # Initialize registries
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        data_dir = os.path.join(base_dir, 'data')
        
        self.commodity_registry = CommodityRegistry()
        commodities_path = os.path.join(data_dir, 'commodities.yaml')
        if os.path.exists(commodities_path):
            self.commodity_registry.load_from_file(commodities_path)
        
        self.process_registry = ProcessRegistry(self.commodity_registry)
        processes_path = os.path.join(data_dir, 'processes.yaml')
        if os.path.exists(processes_path):
            self.process_registry.load_from_file(processes_path)
            
        self.skills_registry = SkillsRegistry()
        skills_path = os.path.join(data_dir, 'skills.yaml')
        if os.path.exists(skills_path):
            self.skills_registry.load_from_file(skills_path)
        
        # Set this instance as the global instance
        Simulation.instance = self

    def setup_simple(self, num_regular_actors: int = 4, num_market_makers: int = 1, num_ships: int = 2) -> None:
        """Set up a simple simulation with two planets, multiple actors, and ships.

        Args:
            num_regular_actors: Number of regular actors to create per planet
            num_market_makers: Number of market makers to create per planet
            num_ships: Number of ships to create in the simulation
        """
        # Create Earth - positioned near the upper left
        earth = Planet("Earth", x=20.0, y=30.0)
        self.planets.append(earth)
        
        # Create and initialize the market for Earth
        earth_market = Market()
        earth_market.commodity_registry = self.commodity_registry  # Give market access to commodity registry
        earth.market = earth_market
        
        # Create Mars (positioned at a different location)
        mars = Planet("Mars", x=70.0, y=60.0)
        self.planets.append(mars)
        
        # Create and initialize the market for Mars
        mars_market = Market()
        mars_market.commodity_registry = self.commodity_registry  # Give market access to commodity registry
        mars.market = mars_market
        
        # Create actors for Earth
        self._setup_planet_actors(
            planet=earth,
            num_regular_actors=num_regular_actors,
            num_market_makers=num_market_makers,
            actor_name_prefix="Earth"
        )
        
        # Create actors for Mars
        self._setup_planet_actors(
            planet=mars,
            num_regular_actors=num_regular_actors,
            num_market_makers=num_market_makers,
            actor_name_prefix="Mars"
        )
        
        # Give some initial commodities to all actors
        self._distribute_initial_commodities()
            
        # Create ships and distribute them across planets
        self._setup_ships(num_ships)
        
        # Set simulation reference in all actors
        for actor in self.actors:
            actor.sim = self
                
    def _setup_planet_actors(self, planet: Planet, num_regular_actors: int, 
                         num_market_makers: int, actor_name_prefix: str) -> None:
        """Set up actors for a specific planet.
        
        Args:
            planet: The planet to add actors to
            num_regular_actors: Number of regular actors to create
            num_market_makers: Number of market makers to create
            actor_name_prefix: Prefix for actor names
        """
        # Create regular actors with varying production efficiencies and skills
        for i in range(1, num_regular_actors + 1):
            # Random production efficiency between 0.7 and 1.3
            efficiency = random.uniform(0.7, 1.3)
            
            # Generate random initial skills
            initial_skills = {}
            
            # Pick 1-3 skills to specialize in (skills above 1.0)
            num_specialties = random.randint(1, 3)
            all_skills = list(self.skills_registry._skills.keys())
            specialty_skills = random.sample(all_skills, num_specialties)
            
            # Give each actor random skill levels
            for skill_id in all_skills:
                if skill_id in specialty_skills:
                    # Specialties get higher ratings (1.0 to 2.0)
                    initial_skills[skill_id] = random.uniform(1.0, 2.0)
                else:
                    # Other skills get lower ratings (0.5 to 1.0)
                    initial_skills[skill_id] = random.uniform(0.5, 1.0)
            
            actor = Actor(
                name=f"{actor_name_prefix}Colonist-{i}", 
                planet=planet,
                actor_type=ActorType.REGULAR,
                production_efficiency=efficiency,
                initial_money=50,
                initial_skills=initial_skills
            )
            self.actors.append(actor)
            planet.add_actor(actor)

        # Create market makers with balanced skills
        for i in range(1, num_market_makers + 1):
            # Market makers get average skill levels
            initial_skills = {skill_id: 1.0 for skill_id in self.skills_registry._skills.keys()}
            
            actor = Actor(
                name=f"{actor_name_prefix}MarketMaker-{i}", 
                planet=planet,
                actor_type=ActorType.MARKET_MAKER,
                initial_money=200,
                initial_skills=initial_skills
            )
            self.actors.append(actor)
            planet.add_actor(actor)
    
    def _distribute_initial_commodities(self) -> None:
        """Distribute initial commodities to actors."""
        # Get all commodities from registry
        food = self.commodity_registry.get_commodity("food")
        biomass = self.commodity_registry.get_commodity("biomass")
        simple_tools = self.commodity_registry.get_commodity("simple_tools")
        nova_fuel = self.commodity_registry.get_commodity("nova_fuel")
        nova_fuel_ore = self.commodity_registry.get_commodity("nova_fuel_ore")
        common_metal = self.commodity_registry.get_commodity("common_metal")
        common_metal_ore = self.commodity_registry.get_commodity("common_metal_ore")
        simple_building_materials = self.commodity_registry.get_commodity("simple_building_materials")
        metalworking_facility = self.commodity_registry.get_commodity("metalworking_facility")
        smelting_facility = self.commodity_registry.get_commodity("smelting_facility")
        
        # Give some initial commodities to market makers to jumpstart the market
        for actor in self.actors:
            if actor.actor_type == ActorType.MARKET_MAKER:
                # Give food and resources
                if food:
                    actor.inventory.add_commodity(food, 20)
                if biomass:
                    actor.inventory.add_commodity(biomass, 30)
                if simple_tools:
                    actor.inventory.add_commodity(simple_tools, 5)
                if nova_fuel:
                    actor.inventory.add_commodity(nova_fuel, 15)
                if nova_fuel_ore:
                    actor.inventory.add_commodity(nova_fuel_ore, 20)
                if common_metal:
                    actor.inventory.add_commodity(common_metal, 10)
                if common_metal_ore:
                    actor.inventory.add_commodity(common_metal_ore, 15)
                if simple_building_materials:
                    actor.inventory.add_commodity(simple_building_materials, 15)
                
                # Give market makers some facilities to jumpstart production
                if metalworking_facility:
                    actor.inventory.add_commodity(metalworking_facility, 1)
                if smelting_facility:
                    actor.inventory.add_commodity(smelting_facility, 1)
                
        # Give regular actors some commodities to get started
        for i, actor in enumerate(self.actors):
            if actor.actor_type == ActorType.REGULAR:
                # Basic food and resources
                if food:
                    actor.inventory.add_commodity(food, 3)
                if biomass:
                    actor.inventory.add_commodity(biomass, 5)
                
                # Give a small amount of fuel and tools to some actors to seed production
                if random.random() < 0.5:  # 50% chance
                    if nova_fuel:
                        actor.inventory.add_commodity(nova_fuel, 1)
                    if simple_tools:
                        actor.inventory.add_commodity(simple_tools, 1)
                
                # Give some regular actors facilities (one in four)
                if i % 4 == 0 and smelting_facility:
                    actor.inventory.add_commodity(smelting_facility, 1)
                elif i % 4 == 1 and metalworking_facility:
                    actor.inventory.add_commodity(metalworking_facility, 1)

    def _setup_ships(self, num_ships: int) -> None:
        """Set up ships for the simulation.
        
        Args:
            num_ships: Number of ships to create
        """
        if not self.planets:
            return
            
        # Create ships with varying fuel efficiency
        for i in range(1, num_ships + 1):
            # Random fuel efficiency between 0.8 and 1.2
            efficiency = random.uniform(0.8, 1.2)
            
            # Randomly assign a starting planet
            planet = random.choice(self.planets)
            
            ship = Ship(
                name=f"Trader-{i}",
                planet=planet,
                fuel_efficiency=efficiency,
                initial_money=1000
            )
            
            # Give ships some starting fuel
            nova_fuel = self.commodity_registry.get_commodity("nova_fuel")
            if nova_fuel:
                ship.cargo.add_commodity(nova_fuel, 30)
            
            # Add ship to simulation and planet
            self.ships.append(ship)
            planet.add_ship(ship)
            
            # Set simulation reference
            ship.simulation = self
    
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
        
        # Randomize ship order
        random.shuffle(self.ships)
        
        # Each ship takes their turn
        for ship in self.ships:
            ship.take_turn()
            
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
                
                # Note: Orders are now persistent across turns

    def _record_market_stats(self, planet: Planet) -> None:
        """Record market statistics for analysis."""
        if not planet.market:
            return
            
        market = planet.market
        
        # Initialize stats dictionary if needed
        if planet.name not in self.market_stats:
            self.market_stats[planet.name] = {
                "food_prices": [],
                "food_transactions": [],
                "food_volume": [],
                "fuel_prices": [],
                "fuel_transactions": [],
                "fuel_volume": []
            }
        
        # Get commodities by ID
        food_commodity = self.commodity_registry.get_commodity("food")
        fuel_commodity = self.commodity_registry.get_commodity("nova_fuel")
        
        if food_commodity and fuel_commodity:
            # Record food stats
            food_price = market.get_avg_price(food_commodity)
            food_transactions = sum(
                1 for t in market.transaction_history 
                if t.commodity_type == food_commodity or 
                (isinstance(t.commodity_type, str) and t.commodity_type == "food")
            )
            food_volume = sum(
                t.quantity for t in market.transaction_history 
                if t.commodity_type == food_commodity or 
                (isinstance(t.commodity_type, str) and t.commodity_type == "food")
            )
            
            self.market_stats[planet.name]["food_prices"].append(food_price)
            self.market_stats[planet.name]["food_transactions"].append(food_transactions)
            self.market_stats[planet.name]["food_volume"].append(food_volume)
            
            # Record fuel stats
            fuel_price = market.get_avg_price(fuel_commodity)
            fuel_transactions = sum(
                1 for t in market.transaction_history 
                if t.commodity_type == fuel_commodity or 
                (isinstance(t.commodity_type, str) and t.commodity_type == "nova_fuel")
            )
            fuel_volume = sum(
                t.quantity for t in market.transaction_history 
                if t.commodity_type == fuel_commodity or 
                (isinstance(t.commodity_type, str) and t.commodity_type == "nova_fuel")
            )
            
            self.market_stats[planet.name]["fuel_prices"].append(fuel_price)
            self.market_stats[planet.name]["fuel_transactions"].append(fuel_transactions)
            self.market_stats[planet.name]["fuel_volume"].append(fuel_volume)

    def run_simulation(self, num_turns: int) -> None:
        """Run the simulation for a specified number of turns."""
        for _ in range(num_turns):
            self.run_turn()

    def _print_status(self) -> None:
        """Print the current status of the simulation."""
        # First list all traveling ships since they're not tied to a specific planet at the moment
        traveling_ships = [ship for ship in self.ships if ship.status == ShipStatus.TRAVELING]
        if traveling_ships:
            print("Ships in transit:")
            for ship in traveling_ships:
                if ship.destination:
                    destination_name = ship.destination.name
                    progress_percent = int(ship.travel_progress * 100)
                    print(f"  {ship.name}: En route to {destination_name} ({progress_percent}% complete)")
                    
                    # Get commodity quantities
                    food_commodity = self.commodity_registry.get_commodity("food")
                    fuel_commodity = self.commodity_registry.get_commodity("nova_fuel")
                    food_qty = ship.cargo.get_quantity(food_commodity) if food_commodity else 0
                    fuel_qty = ship.cargo.get_quantity(fuel_commodity) if fuel_commodity else 0
                    
                    print(f"    Cargo: {food_qty} food, {fuel_qty} fuel")
                    print(f"    Money: {ship.money} credits")
                    print(f"    Status: {ship.last_action}")
        
        # Now list planets and their contents
        for planet in self.planets:
            print(f"Planet: {planet.name}")
            
            # Calculate market statistics if available
            if planet.market:
                food_commodity = self.commodity_registry.get_commodity("food")
                fuel_commodity = self.commodity_registry.get_commodity("nova_fuel")
                if food_commodity and fuel_commodity:
                    food_price = planet.market.get_avg_price(food_commodity)
                    fuel_price = planet.market.get_avg_price(fuel_commodity)
                    print(f"  Market: Food Price: {food_price}, Fuel Price: {fuel_price}")
                
                # Print current turn's transactions only
                if planet.market.transaction_history:
                    # Filter transactions from current turn only
                    current_turn_transactions = [tx for tx in planet.market.transaction_history if getattr(tx, 'turn', 0) == self.current_turn]
                    
                    if current_turn_transactions:
                        print(f"  Transactions this turn:")
                        for tx in current_turn_transactions:
                            # Handle string or object commodity type
                            if hasattr(tx.commodity_type, 'name'):
                                commodity_name = tx.commodity_type.name
                            else:
                                commodity_name = str(tx.commodity_type)
                            print(f"    {tx.buyer.name} bought {tx.quantity} {commodity_name} from {tx.seller.name} @ {tx.price}")
                    else:
                        print("  No transactions this turn")
                else:
                    print("  No transactions yet")
            
            # Print actor status
            for actor in planet.actors:
                # Get commodity quantities
                food_commodity = self.commodity_registry.get_commodity("food")
                biomass_commodity = self.commodity_registry.get_commodity("biomass")
                tools_commodity = self.commodity_registry.get_commodity("simple_tools")
                fuel_commodity = self.commodity_registry.get_commodity("nova_fuel")
                metal_commodity = self.commodity_registry.get_commodity("common_metal")
                metal_ore_commodity = self.commodity_registry.get_commodity("common_metal_ore")
                
                # Get quantities
                food_qty = actor.inventory.get_quantity(food_commodity) if food_commodity else 0
                biomass_qty = actor.inventory.get_quantity(biomass_commodity) if biomass_commodity else 0
                tools_qty = actor.inventory.get_quantity(tools_commodity) if tools_commodity else 0
                fuel_qty = actor.inventory.get_quantity(fuel_commodity) if fuel_commodity else 0
                metals_qty = actor.inventory.get_quantity(metal_commodity) if metal_commodity else 0
                metal_ore_qty = actor.inventory.get_quantity(metal_ore_commodity) if metal_ore_commodity else 0
                
                # Fall back to string IDs if needed
                if food_qty == 0 and isinstance(food_commodity, str):
                    food_qty = actor.inventory.get_quantity("food")
                if biomass_qty == 0 and isinstance(biomass_commodity, str):
                    biomass_qty = actor.inventory.get_quantity("biomass")
                if tools_qty == 0 and isinstance(tools_commodity, str):
                    tools_qty = actor.inventory.get_quantity("simple_tools")
                if fuel_qty == 0 and isinstance(fuel_commodity, str):
                    fuel_qty = actor.inventory.get_quantity("nova_fuel")
                if metals_qty == 0 and isinstance(metal_commodity, str):
                    metals_qty = actor.inventory.get_quantity("common_metal")
                if metal_ore_qty == 0 and isinstance(metal_ore_commodity, str):
                    metal_ore_qty = actor.inventory.get_quantity("common_metal_ore")
                
                food_status = "✓" if actor.food_consumed_this_turn else "✗"
                
                # Show actor's last action
                action = actor.last_action
                
                # Check for facilities
                smelting = actor.inventory.get_quantity("smelting_facility")
                metalworking = actor.inventory.get_quantity("metalworking_facility")
                facilities_str = ""
                if smelting > 0 or metalworking > 0:
                    facility_parts = []
                    if smelting > 0:
                        facility_parts.append(f"Smelting:{smelting}")
                    if metalworking > 0:
                        facility_parts.append(f"Metalworking:{metalworking}")
                    facilities_str = f", Facilities:[{', '.join(facility_parts)}]"
                
                # Get top skills to display (skills with rating > 1.0)
                top_skills = []
                for skill_id, rating in actor.skills.items():
                    if rating > 1.0:
                        top_skills.append(f"{skill_id.split('_')[0][:3]}:{rating:.1f}")
                skills_str = f", Skills:[{', '.join(top_skills)}]" if top_skills else ""
                
                # Show market maker status differently
                if actor.actor_type == ActorType.MARKET_MAKER:
                    print(f"  [MM] {actor.name}: ${actor.money}, Food:{food_qty}{food_status}, Bio:{biomass_qty}, Action:{action}{facilities_str}{skills_str}")
                else:
                    print(f"  {actor.name}: ${actor.money}, Food:{food_qty}{food_status}, Bio:{biomass_qty}, " +
                          f"Tools:{tools_qty}, Metal:{metals_qty}, MetalOre:{metal_ore_qty}, Fuel:{fuel_qty}, Action:{action}{facilities_str}{skills_str}")
            
            # Print ship status for ships at this planet
            if planet.ships:
                print(f"  Ships docked at {planet.name}:")
                for ship in planet.ships:
                    print(f"    {ship.name}: {ship.money} credits")
                    
                    # Get commodity quantities
                    food_commodity = self.commodity_registry.get_commodity("food")
                    fuel_commodity = self.commodity_registry.get_commodity("nova_fuel")
                    food_qty = ship.cargo.get_quantity(food_commodity) if food_commodity else 0
                    fuel_qty = ship.cargo.get_quantity(fuel_commodity) if fuel_commodity else 0
                    
                    print(f"      Cargo: {food_qty} food, {fuel_qty} fuel")
                    print(f"      Status: {ship.last_action}")
                
            # Count hunger
            hungry_count = sum(1 for a in planet.actors if not a.food_consumed_this_turn)
            if hungry_count > 0:
                print(f"  {hungry_count} actors couldn't eat this turn!")