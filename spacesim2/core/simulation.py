import random
import math
from pathlib import Path
from typing import List, Dict, Tuple

from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.brains import ColonistBrain, MarketMakerBrain
from spacesim2.core.commodity import CommodityRegistry
from spacesim2.core.data_logger import DataLogger
from spacesim2.core.drives import FoodDrive, ClothingDrive, ShelterDrive
from spacesim2.core.process import ProcessRegistry
from spacesim2.core.market import Market
from spacesim2.core.planet import Planet
from spacesim2.core.ship import Ship, ShipStatus
from spacesim2.core.skill import SkillsRegistry


class Simulation:
    """Main simulation controller."""
    def __init__(self) -> None:
        self.planets: List[Planet] = []
        self.actors: List[Actor] = []
        self.ships: List[Ship] = []
        self.current_turn = 0
        self.market_stats: Dict = {}  # Track market statistics
        
        # Initialize registries
        #base_dir = Path(__file__).parent.parent.parent
        #data_dir = base_dir / 'data'
        data_dir = Path('data') 
        commodities_path = data_dir / 'commodities.yaml'
        processes_path = data_dir / 'processes.yaml'
        skills_path = data_dir / 'skills.yaml'

        self.commodity_registry = CommodityRegistry()
        self.commodity_registry.load_from_file(commodities_path)
        
        self.process_registry = ProcessRegistry(self.commodity_registry)
        self.process_registry.load_from_file(processes_path)
            
        self.skills_registry = SkillsRegistry()
        self.skills_registry.load_from_file(skills_path)

        self.data_logger = DataLogger()
        
    def _generate_fictional_planets(self, num_planets: int) -> List[Tuple[str, float, float]]:
        """Generate fictional planet names and positions with minimum 10 unit separation.
        
        Args:
            num_planets: Number of planets to generate
            
        Returns:
            List of tuples containing (name, x, y) for each planet
        """
        # Collection of fictional planet names from various sci-fi sources
        fictional_names = [
            "Drakoon", "Veyrahn", "Korrith", "Jandrak", "Thazuun", "Marrakos", "Zethar", "Xoroq", "Bal’drahn", "Quorrin",
            "Endahlis", "Veyndor", "Liranna", "Koshava", "Bren’drel", "Orivaan", "Sylith", "Quenara", "Thaelwyn", "Yorrak",
            "Thalassa", "Myrren", "Korvannis", "Aelithar", "Voruna", "Kalyss", "Drennok", "Oquara", "Zorathis", "Fen’lor",
            "Vrynnos", "Shalvek", "Droskaar", "Arveth", "Krylos", "Vintarra", "Malqor", "Zeyrik", "Korenth", "Thaazek",
            "Dravik", "Corvenn", "Helkross", "Tyrranos", "Velcorra", "Oxenn Prime", "Grenthis", "Calbrak", "Drosmir", "Xyphara",
            "Zalith", "Onakorr", "Yrivaan", "Votharis", "Kaelthuun", "Ombera", "Kythorr", "Ruunas", "Elvorra", "Shyrrak",
            "Branoth", "Jekarra", "Zyndralis", "Vornakk", "Pellosh", "Quorrahn", "Tavrelis", "Korrithos", "Drethuun", "Xeylon",
            "Alvara", "Serenith", "Valdorei", "Olyssian", "Trinorra", "Eryllan", "Feyriss", "Solvane", "Quenalis", "Marrosyn",
            "Krassith", "Vondrak", "Barrekos", "Dravoss", "Ulthar", "Zorran Prime", "Makreth", "Syrrik", "Kolthuun", "Vashrik",
            "Iyora", "Qethar", "Zhaluun", "Drevari", "Othwyn", "Pyrassos", "Venorra", "Kyrathis", "Jorvess", "Thaelkor"
        ]
        
        # Ensure we don't request more planets than we have names
        num_planets = min(num_planets, len(fictional_names))
        
        # Randomly select planet names
        selected_names = random.sample(fictional_names, num_planets)
        
        # Generate positions with minimum 10 unit separation
        positions = self._generate_separated_positions(num_planets, min_distance=10.0, map_size=100.0)
        
        return list(zip(selected_names, [pos[0] for pos in positions], [pos[1] for pos in positions]))
    
    def _generate_separated_positions(self, num_positions: int, min_distance: float, map_size: float) -> List[Tuple[float, float]]:
        """Generate positions with minimum distance separation using Poisson disc sampling approach.
        
        Args:
            num_positions: Number of positions to generate
            min_distance: Minimum distance between positions
            map_size: Size of the map (square area from 0 to map_size)
            
        Returns:
            List of (x, y) positions
        """
        positions = []
        max_attempts = 1000  # Prevent infinite loops
        attempts = 0
        
        while len(positions) < num_positions and attempts < max_attempts:
            # Generate random position
            x = random.uniform(min_distance, map_size - min_distance)
            y = random.uniform(min_distance, map_size - min_distance)
            
            # Check distance to all existing positions
            valid = True
            for existing_x, existing_y in positions:
                distance = math.sqrt((x - existing_x)**2 + (y - existing_y)**2)
                if distance < min_distance:
                    valid = False
                    break
            
            if valid:
                positions.append((x, y))
            
            attempts += 1
        
        # If we couldn't generate enough positions, warn and return what we have
        if len(positions) < num_positions:
            print(f"Warning: Could only generate {len(positions)} positions out of {num_positions} requested with min_distance={min_distance}")
        
        return positions

    def setup_simple(self, num_planets: int = 2, num_regular_actors: int = 4, num_market_makers: int = 1, num_ships: int = 2) -> None:
        """Set up a simple simulation with multiple planets, actors, and ships.

        Args:
            num_planets: Number of planets to create
            num_regular_actors: Number of regular actors to create per planet
            num_market_makers: Number of market makers to create per planet
            num_ships: Number of ships to create in the simulation
        """
        # Generate fictional planet data with random positions
        planet_data = self._generate_fictional_planets(num_planets)
        
        # Create the planets with their markets
        for name, x, y in planet_data:
            # Create and initialize the market for the planet
            planet_market = Market()
            planet_market.commodity_registry = self.commodity_registry  # Give market access to commodity registry
            planet = Planet(name, planet_market, x=x, y=y)
            self.planets.append(planet)
            
            # Create actors for each planet
            self._setup_planet_actors(
                planet=planet,
                num_regular_actors=num_regular_actors,
                num_market_makers=num_market_makers,
                actor_name_prefix=name
            )
        
        # Create ships and distribute them across planets
        self._setup_ships(num_ships)
        
        # Simulation references already set in constructors
                
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

            # Initialize actor drives
            drives = [Drive(commodity_registry=self.commodity_registry) 
                      for Drive in (FoodDrive, ClothingDrive, ShelterDrive)]

            actor = Actor(
                name=f"{actor_name_prefix}Colonist-{i}",
                sim=self,
                planet=planet,
                actor_type=ActorType.REGULAR,
                brain=ColonistBrain(),
                drives=drives,
                initial_money=50,
                initial_skills=initial_skills
            )
            self.actors.append(actor)
            planet.add_actor(actor)

        # Create market makers with balanced skills
        for i in range(num_market_makers):
            # Market makers get average skill levels
            initial_skills = {skill_id: 1.0 for skill_id in self.skills_registry._skills.keys()}

            # Initialize actor drives
            drives = [Drive(commodity_registry=self.commodity_registry) 
                      for Drive in (FoodDrive, ClothingDrive, ShelterDrive)]
            
            actor = Actor(
                name=f"{actor_name_prefix}MarketMaker-{i+1}",
                sim=self,
                planet=planet,
                drives=[],
                actor_type=ActorType.MARKET_MAKER,
                brain=MarketMakerBrain(),
                initial_money=200,
                initial_skills=initial_skills
            )
            self.actors.append(actor)
            planet.add_actor(actor)

    def _setup_ships(self, num_ships: int) -> None:
        """Set up ships for the simulation.
        
        Args:
            num_ships: Number of ships to create
        """
        if not self.planets:
            return
        
        # Scale the number of ships based on the number of planets
        adjusted_num_ships = num_ships * len(self.planets) // 2
            
        # Create ships with varying fuel efficiency
        for i in range(adjusted_num_ships):
            # Random fuel efficiency between 0.8 and 1.2
            efficiency = random.uniform(0.8, 1.2)
            
            # Randomly assign a starting planet
            planet = random.choice(self.planets)
            
            ship = Ship(
                name=f"Trader-{i+1}",
                simulation=self,
                planet=planet,
                fuel_efficiency=efficiency,
                initial_money=1000
            )
            
            # Give ships some starting fuel
            nova_fuel = self.commodity_registry["nova_fuel"]
            ship.cargo.add_commodity(nova_fuel, 30)
            
            # Add ship to simulation and planet
            self.ships.append(ship)
            planet.add_ship(ship)
            
            # Simulation reference already set in constructor
    
    def run_turn(self) -> None:
        """Run a single turn of the simulation."""
        self.current_turn += 1
        self.data_logger.set_turn(self.current_turn)
        print(f"\n=== Turn {self.current_turn} ===")

        # Update market turn counters
        for planet in self.planets:
            # Market is guaranteed to exist
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
            # Market is guaranteed to exist
                # Execute trades
                planet.market.match_orders()
                
                
    def run_simulation(self, num_turns: int) -> None:
        """Run the simulation for a specified number of turns."""
        for _ in range(num_turns):
            self.run_turn()

    def _print_status(self) -> None:
        """Print the current status of the simulation."""
        print(f"\n=== Turn {self.current_turn} Summary ===")

        # Count total actors and ships
        total_actors = len(self.actors)
        market_makers = sum(1 for a in self.actors if a.actor_type == ActorType.MARKET_MAKER)
        regular_actors = total_actors - market_makers
        total_ships = len(self.ships)
        traveling_ships = sum(1 for s in self.ships if s.status == ShipStatus.TRAVELING)
        
        # Count hunger
        total_hungry = sum(1 for a in self.actors if not a.food_consumed_this_turn)
        hungry_percent = (total_hungry / total_actors * 100) if total_actors > 0 else 0
        
        # Print simulation stats
        planet_names = ", ".join([p.name for p in self.planets])
        print(f"Planets ({len(self.planets)}): {planet_names}")
        print(f"Population: {regular_actors} colonists, {market_makers} market makers")
        print(f"Ships: {total_ships} total, {traveling_ships} in transit")
        print(f"Hunger: {total_hungry}/{total_actors} actors hungry ({hungry_percent:.1f}%)")