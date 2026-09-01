import math
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.brains import ColonistBrain, IndustrialistBrain, MarketMakerBrain
from spacesim2.core.commodity import CommodityRegistry
from spacesim2.core.data_logger import DataLogger
from spacesim2.core.drives import (
    ActorDrive,
    ClothingDrive,
    FoodDrive,
    HealthDrive,
    ShelterDrive,
)
from spacesim2.core.market import Market
from spacesim2.core.planet import Planet
from spacesim2.core.planet_attributes import PlanetAttributes
from spacesim2.core.process import ProcessRegistry
from spacesim2.core.ship import Ship
from spacesim2.core.skill import SkillsRegistry

if TYPE_CHECKING:
    from spacesim2.analysis.export.exporter import SimulationExporter

# Baseline spatial feel: the historical 5-planet galaxy lived on a 100x100 map.
# We keep that density (area per planet) constant as galaxies grow, so travel
# distances — and therefore fuel economics — feel the same at any scale.
BASE_MAP_SIZE = 100.0
BASE_PLANET_COUNT = 5
AREA_PER_PLANET = (BASE_MAP_SIZE * BASE_MAP_SIZE) / BASE_PLANET_COUNT
MIN_PLANET_DISTANCE = 10.0

# Syllable pools for procedural planet names, used once the curated list of
# fictional names is exhausted (it has ~100 entries).
_NAME_ONSETS = [
    "Kar",
    "Vel",
    "Thal",
    "Zor",
    "Mira",
    "Ques",
    "Dra",
    "Sol",
    "Nem",
    "Ory",
    "Bel",
    "Xan",
    "Tyr",
    "Hal",
    "Jun",
    "Kel",
    "Vor",
    "Ash",
    "Ryn",
    "Ost",
]
_NAME_MIDDLES = [
    "a",
    "e",
    "i",
    "o",
    "u",
    "ar",
    "en",
    "ir",
    "or",
    "un",
    "al",
    "eth",
]
_NAME_CODAS = [
    "dor",
    "vex",
    "mir",
    "thos",
    "rin",
    "nax",
    "lis",
    "gar",
    "von",
    "tis",
    "kar",
    "dune",
    "prime",
    "moor",
    "reth",
    "sil",
    "quor",
    "bane",
    "loth",
    "wyn",
]

# Market makers must provide two-sided liquidity across *every* transportable
# commodity, including illiquid upper-tier goods that have no organic supply yet.
# Their starting capital is therefore scaled to the number of markets they serve
# rather than a flat amount, so per-market depth stays meaningful as the
# commodity tree grows. See MarketMakerBrain for how this pool is allocated.
MARKET_MAKER_CAPITAL_PER_MARKET = 100


class Simulation:
    """Main simulation controller."""

    def __init__(self) -> None:
        self.planets: List[Planet] = []
        self.actors: List[Actor] = []
        self.ships: List[Ship] = []
        self.current_turn = 0
        # Threaded actor phase (core/parallel.py). >1 shards planets across
        # a thread pool; real speedup needs a free-threaded interpreter.
        # See docs/performance.md.
        self.parallel_workers: int = 1
        self._actor_phase_pool: Optional[ThreadPoolExecutor] = None
        self._actor_phase_pool_size: int = 0

        # Initialize registries
        # base_dir = Path(__file__).parent.parent.parent
        # data_dir = base_dir / 'data'
        data_dir = Path("data")
        commodities_path = data_dir / "commodities.yaml"
        processes_path = data_dir / "processes.yaml"
        skills_path = data_dir / "skills.yaml"

        self.commodity_registry = CommodityRegistry()
        self.commodity_registry.load_from_file(commodities_path)

        self.process_registry = ProcessRegistry(self.commodity_registry)
        self.process_registry.load_from_file(processes_path)

        self.skills_registry = SkillsRegistry()
        self.skills_registry.load_from_file(skills_path)

        self.data_logger = DataLogger()
        self.exporter: Optional["SimulationExporter"] = None

    def _generate_fictional_planets(
        self, num_planets: int
    ) -> List[Tuple[str, float, float]]:
        """Generate fictional planet names and positions with minimum 10 unit separation.

        Args:
            num_planets: Number of planets to generate

        Returns:
            List of tuples containing (name, x, y) for each planet
        """
        # Collection of fictional planet names from various sci-fi sources
        fictional_names = [
            "Drakoon",
            "Veyrahn",
            "Korrith",
            "Jandrak",
            "Thazuun",
            "Marrakos",
            "Zethar",
            "Xoroq",
            "Bal’drahn",
            "Quorrin",
            "Endahlis",
            "Veyndor",
            "Liranna",
            "Koshava",
            "Bren’drel",
            "Orivaan",
            "Sylith",
            "Quenara",
            "Thaelwyn",
            "Yorrak",
            "Thalassa",
            "Myrren",
            "Korvannis",
            "Aelithar",
            "Voruna",
            "Kalyss",
            "Drennok",
            "Oquara",
            "Zorathis",
            "Fen’lor",
            "Vrynnos",
            "Shalvek",
            "Droskaar",
            "Arveth",
            "Krylos",
            "Vintarra",
            "Malqor",
            "Zeyrik",
            "Korenth",
            "Thaazek",
            "Dravik",
            "Corvenn",
            "Helkross",
            "Tyrranos",
            "Velcorra",
            "Oxenn Prime",
            "Grenthis",
            "Calbrak",
            "Drosmir",
            "Xyphara",
            "Zalith",
            "Onakorr",
            "Yrivaan",
            "Votharis",
            "Kaelthuun",
            "Ombera",
            "Kythorr",
            "Ruunas",
            "Elvorra",
            "Shyrrak",
            "Branoth",
            "Jekarra",
            "Zyndralis",
            "Vornakk",
            "Pellosh",
            "Quorrahn",
            "Tavrelis",
            "Korrithos",
            "Drethuun",
            "Xeylon",
            "Alvara",
            "Serenith",
            "Valdorei",
            "Olyssian",
            "Trinorra",
            "Eryllan",
            "Feyriss",
            "Solvane",
            "Quenalis",
            "Marrosyn",
            "Krassith",
            "Vondrak",
            "Barrekos",
            "Dravoss",
            "Ulthar",
            "Zorran Prime",
            "Makreth",
            "Syrrik",
            "Kolthuun",
            "Vashrik",
            "Iyora",
            "Qethar",
            "Zhaluun",
            "Drevari",
            "Othwyn",
            "Pyrassos",
            "Venorra",
            "Kyrathis",
            "Jorvess",
            "Thaelkor",
        ]

        if num_planets < 1:
            raise ValueError(f"num_planets must be >= 1, got {num_planets}")

        # Use the curated names first, then fall back to procedural names so
        # any galaxy size gets unique, readable names.
        if num_planets <= len(fictional_names):
            selected_names = random.sample(fictional_names, num_planets)
        else:
            selected_names = random.sample(fictional_names, len(fictional_names))
            used = set(selected_names)
            while len(selected_names) < num_planets:
                name = self._generate_procedural_name(used)
                used.add(name)
                selected_names.append(name)

        # Generate positions, scaling the map with planet count so spatial
        # density (and travel/fuel economics) stays constant.
        map_size = max(BASE_MAP_SIZE, math.sqrt(AREA_PER_PLANET * num_planets))
        positions = self._generate_separated_positions(
            num_planets, min_distance=MIN_PLANET_DISTANCE, map_size=map_size
        )

        return list(
            zip(
                selected_names,
                [pos[0] for pos in positions],
                [pos[1] for pos in positions],
            )
        )

    @staticmethod
    def _generate_procedural_name(used: set[str]) -> str:
        """Generate a unique, readable procedural planet name.

        Combines onset/middle/coda syllables (e.g. "Karendor", "Velvex");
        collisions retry with fresh syllables, and after a bounded number of
        attempts a numeric suffix guarantees uniqueness.

        Args:
            used: Names already taken; the returned name is not in this set.

        Returns:
            A unique planet name.
        """
        for _ in range(100):
            name = random.choice(_NAME_ONSETS)
            if random.random() < 0.5:
                name += random.choice(_NAME_MIDDLES)
            name += random.choice(_NAME_CODAS)
            name = name.capitalize()
            if name not in used:
                return name
        # Extremely unlikely fallback: append a counter for guaranteed uniqueness.
        base = name
        suffix = 2
        while f"{base}-{suffix}" in used:
            suffix += 1
        return f"{base}-{suffix}"

    def _generate_separated_positions(
        self, num_positions: int, min_distance: float, map_size: float
    ) -> List[Tuple[float, float]]:
        """Generate positions with guaranteed minimum pairwise separation.

        Rejection sampling is tried first: it reproduces the historical spatial
        distribution (uniform with clustering allowed down to ``min_distance``),
        which the fuel/travel economics were tuned against. Because the caller
        scales the map area with the position count, rejection almost always
        succeeds quickly. If it cannot complete within its attempt budget, a
        jittered-grid sampler takes over — O(n) and guaranteed to fit whenever
        the grid cells are at least ``min_distance`` wide.

        Args:
            num_positions: Number of positions to generate.
            min_distance: Minimum pairwise distance between positions.
            map_size: Side length of the square map (coordinates in [0, map_size]).

        Returns:
            List of exactly ``num_positions`` (x, y) positions.

        Raises:
            ValueError: If the requested count cannot fit on the map with the
                given minimum distance.
        """
        if num_positions < 1:
            raise ValueError(f"num_positions must be >= 1, got {num_positions}")

        rejection = self._rejection_sample_positions(
            num_positions, min_distance, map_size
        )
        if len(rejection) == num_positions:
            return rejection

        return self._jittered_grid_positions(num_positions, min_distance, map_size)

    @staticmethod
    def _rejection_sample_positions(
        num_positions: int, min_distance: float, map_size: float
    ) -> List[Tuple[float, float]]:
        """Rejection-sample separated positions; may return fewer than requested.

        Candidates are drawn uniformly from [min_distance, map_size - min_distance]
        (matching the legacy sampler) and kept if at least ``min_distance`` from
        every accepted position. Gives up after a bounded attempt budget so a
        too-dense request degrades to the caller's fallback instead of spinning.

        Args:
            num_positions: Number of positions requested.
            min_distance: Minimum pairwise distance between positions.
            map_size: Side length of the square map.

        Returns:
            List of up to ``num_positions`` (x, y) positions.
        """
        low, high = min_distance, map_size - min_distance
        if high <= low:
            return []

        positions: List[Tuple[float, float]] = []
        max_attempts = max(1000, 40 * num_positions)
        for _ in range(max_attempts):
            x = random.uniform(low, high)
            y = random.uniform(low, high)
            if all(math.hypot(x - ex, y - ey) >= min_distance for ex, ey in positions):
                positions.append((x, y))
                if len(positions) == num_positions:
                    break
        return positions

    @staticmethod
    def _jittered_grid_positions(
        num_positions: int, min_distance: float, map_size: float
    ) -> List[Tuple[float, float]]:
        """Place separated positions on a jittered grid; guaranteed to fit or raise.

        The map is divided into a k x k grid (k = ceil(sqrt(num_positions))),
        ``num_positions`` cells are chosen at random, and one point is jittered
        inside each cell while keeping a margin of ``min_distance / 2`` from the
        cell edges. Points in distinct cells are then at least ``min_distance``
        apart, so generation is O(n) with no retry loop.

        Args:
            num_positions: Number of positions to generate.
            min_distance: Minimum pairwise distance between positions.
            map_size: Side length of the square map.

        Returns:
            List of exactly ``num_positions`` (x, y) positions.

        Raises:
            ValueError: If the grid cells would be narrower than ``min_distance``,
                i.e. the requested count cannot fit on the map.
        """
        grid_side = math.ceil(math.sqrt(num_positions))
        cell_size = map_size / grid_side
        margin = min_distance / 2.0

        if cell_size < min_distance:
            raise ValueError(
                f"Cannot place {num_positions} positions with "
                f"min_distance={min_distance} on a {map_size}x{map_size} map: "
                f"grid cells ({cell_size:.2f}) are smaller than min_distance. "
                f"Increase map_size or reduce the position count."
            )

        chosen_cells = random.sample(range(grid_side * grid_side), num_positions)
        positions: List[Tuple[float, float]] = []
        for cell in chosen_cells:
            col, row = cell % grid_side, cell // grid_side
            x = col * cell_size + random.uniform(margin, cell_size - margin)
            y = row * cell_size + random.uniform(margin, cell_size - margin)
            positions.append((x, y))

        return positions

    def setup_simple(
        self,
        num_planets: int = 2,
        num_regular_actors: int = 4,
        num_market_makers: int = 1,
        num_ships: int = 2,
    ) -> None:
        """Set up a simple simulation with multiple planets, actors, and ships.

        Args:
            num_planets: Number of planets to create
            num_regular_actors: Number of regular actors to create per planet
            num_market_makers: Number of market makers to create per planet
            num_ships: Number of ships to create per planet
        """
        # Generate fictional planet data with random positions
        planet_data = self._generate_fictional_planets(num_planets)

        # Generate planet attributes. Guarantee at least one abundant fuel
        # source: nova_fuel_ore rolls are bimodal, so a galaxy can otherwise
        # come up all-poor (~3% of 5-planet worlds), leaving no viable fuel
        # production anywhere — every ship eventually strands no matter how
        # carefully it plans.
        attribute_rolls = [PlanetAttributes.generate_random() for _ in planet_data]
        if attribute_rolls and all(a.nova_fuel_ore < 0.7 for a in attribute_rolls):
            random.choice(attribute_rolls).nova_fuel_ore = random.uniform(0.7, 1.0)

        # Create the planets with their markets
        for (name, x, y), attributes in zip(planet_data, attribute_rolls):
            # Create and initialize the market for the planet
            planet_market = Market()
            planet_market.commodity_registry = (
                self.commodity_registry
            )  # Give market access to commodity registry
            # Record order events only for actors selected for the logging
            # pipeline (a live view, so --log-actors selection made after
            # setup is honored). See Market.order_event_filter.
            planet_market.order_event_filter = self.data_logger.logged_actor_names()

            planet = Planet(name, planet_market, x=x, y=y, attributes=attributes)
            self.planets.append(planet)

            # Create actors for each planet
            self._setup_planet_actors(
                planet=planet,
                num_regular_actors=num_regular_actors,
                num_market_makers=num_market_makers,
                actor_name_prefix=name,
            )

        # Create ships and distribute them across planets
        self._setup_ships(num_ships)

        # Simulation references already set in constructors

    def _setup_planet_actors(
        self,
        planet: Planet,
        num_regular_actors: int,
        num_market_makers: int,
        actor_name_prefix: str,
    ) -> None:
        """Set up actors for a specific planet.

        Args:
            planet: The planet to add actors to
            num_regular_actors: Number of regular actors to create
            num_market_makers: Number of market makers to create
            actor_name_prefix: Prefix for actor names
        """
        # Create regular actors with varying production efficiencies and skills
        # Split 50/50 between Colonists and Industrialists
        num_colonists = num_regular_actors // 2
        num_industrialists = num_regular_actors - num_colonists

        # Invariant across all actors on this planet — hoisted out of the
        # per-actor loops so setup stays cheap at large populations.
        all_skills = list(self.skills_registry._skills.keys())

        # Create Colonist and Industrialist actors
        regular_actor_specs = [
            ("Colonist", ColonistBrain, num_colonists),
            ("Industrialist", IndustrialistBrain, num_industrialists),
        ]
        for role_name, brain_class, count in regular_actor_specs:
            for i in range(1, count + 1):
                initial_skills = self._random_initial_skills(all_skills)

                # Initialize actor drives
                drives: list[ActorDrive] = [
                    Drive(commodity_registry=self.commodity_registry)
                    for Drive in (FoodDrive, ClothingDrive, ShelterDrive, HealthDrive)
                ]

                actor = Actor(
                    name=f"{actor_name_prefix}{role_name}-{i}",
                    sim=self,
                    planet=planet,
                    actor_type=ActorType.REGULAR,
                    brain=brain_class(),
                    drives=drives,
                    initial_money=50,
                    initial_skills=initial_skills,
                )
                self.actors.append(actor)
                planet.add_actor(actor)

        # Create market makers with balanced skills
        num_markets = sum(
            1 for c in self.commodity_registry.all_commodities() if c.transportable
        )
        market_maker_capital = MARKET_MAKER_CAPITAL_PER_MARKET * max(1, num_markets)

        for i in range(num_market_makers):
            # Market makers get average skill levels
            initial_skills = {skill_id: 1.0 for skill_id in all_skills}

            # Initialize actor drives
            drives = [
                Drive(commodity_registry=self.commodity_registry)
                for Drive in (FoodDrive, ClothingDrive, ShelterDrive, HealthDrive)
            ]

            actor = Actor(
                name=f"{actor_name_prefix}MarketMaker-{i + 1}",
                sim=self,
                planet=planet,
                drives=[],
                actor_type=ActorType.MARKET_MAKER,
                brain=MarketMakerBrain(),
                initial_money=market_maker_capital,
                initial_skills=initial_skills,
            )
            self.actors.append(actor)
            planet.add_actor(actor)

    @staticmethod
    def _random_initial_skills(all_skills: List[str]) -> Dict[str, float]:
        """Roll random initial skill levels with 1-3 specialties.

        Specialty skills rate 1.0-2.0; the rest 0.5-1.0.

        Args:
            all_skills: All skill ids in the registry.

        Returns:
            Mapping of skill id to initial skill level.
        """
        num_specialties = random.randint(1, min(3, len(all_skills)))
        specialty_skills = set(random.sample(all_skills, num_specialties))
        return {
            skill_id: random.uniform(1.0, 2.0)
            if skill_id in specialty_skills
            else random.uniform(0.5, 1.0)
            for skill_id in all_skills
        }

    def _setup_ships(self, num_ships: int) -> None:
        """Set up ships for the simulation.

        Args:
            num_ships: Number of ships to create per planet
        """
        if not self.planets:
            return

        # Create num_ships per planet
        total_ships = num_ships * len(self.planets)

        # Create ships with varying fuel efficiency
        for i in range(total_ships):
            # Random fuel efficiency between 0.8 and 1.2
            efficiency = random.uniform(0.8, 1.2)

            # Randomly assign a starting planet
            planet = random.choice(self.planets)

            ship = Ship(
                name=f"Trader-{i + 1}",
                simulation=self,
                planet=planet,
                fuel_efficiency=efficiency,
                initial_money=1000,
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
        # Update market turn counters
        for planet in self.planets:
            # Market is guaranteed to exist
            planet.market.set_current_turn(self.current_turn)

        if self.parallel_workers > 1 and len(self.planets) >= 2:
            from spacesim2.core.parallel import run_actor_phase_threaded

            run_actor_phase_threaded(self, self.parallel_workers)
        else:
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

        # Export data if exporter is attached
        if self.exporter:
            self.exporter.export_turn(self, self.current_turn)

    def _process_markets(self) -> None:
        """Process all markets at the end of the turn."""
        for planet in self.planets:
            # Market is guaranteed to exist
            # Execute trades
            planet.market.match_orders()
