Skill-Based Process Model

Actors possess general Skills that influence multiple processes, allowing flexibility and intuitive modeling of expertise across related processes.
Example Skills:

    Mining (Extracting ores and minerals)

    Refining (Smelting metals, refining fuels)

    Simple Manufacturing (Making simple tools, building materials)

    Advanced Manufacturing (Complex facilities, high-tech tools)

    Agriculture (Growing biomass, making food)

    Culinary (Preparing specialized food and consumables)

    Aerospace (Fuel refinement, starship maintenance, building spacecraft)

    Chemistry (Processing chemicals, pharmaceuticals, advanced fuels)

Mapping Skills to Processes:

Each process links clearly to one or more skills. Actors have skill ratings that influence process efficiency and outcomes.

Example mapping:
Process	Relevant Skill(s)
Mine Ore	Mining
Refine Common Metal	Refining
Refine NovaFuel	Chemistry, Aerospace, Refining
Make Simple Tools	Simple Manufacturing
Gather Biomass	Agriculture
Make Food	Culinary, Agriculture

    Processes referencing multiple skills use the average skill rating of involved skills.

Skill Ratings & Effects:

Skill ratings range typically from 0.5 (unskilled) to 3.0 (highly skilled):

    Skill ratings impact:

        Success rate (below 1.0, risk of process failure).

        Process multiplier chance (above 1.0, chance to increase inputs and outputs).

Success Probability:

    Skill rating ≥ 1.0: 100% success.

    Skill rating < 1.0: Success probability proportional to rating (e.g., 0.8 rating → 80% success chance).

Multiplier Probability:

    Calculated based on skill rating, e.g.:
    Multiplier Chance=(Skill Rating−1.0)×50%
    Multiplier Chance=(Skill Rating−1.0)×50%

Skill Rating	Multiplier Chance
1.0	0%
1.5	25%
2.0	50%
3.0+	100%

    Multiplier increases both inputs and outputs proportionally (typically ×2).

Example Scenario:

Actor with skills:

skills:
  Mining: 2.0
  Refining: 1.2
  Simple Manufacturing: 0.8

Example 1: Mine Ore (Mining: 2.0):

    Success: 100%

    Multiplier chance: 50% (2.0 - 1.0) × 50%

Possible outcomes:
Outcome	Probability	Inputs	Outputs
Normal (×1)	50%	None	2 Common Ore, 1 NovaFuel Ore
Multiplier (×2)	50%	None	4 Common Ore, 2 NovaFuel Ore
Example 2: Refine Common Metal (Refining: 1.2):

    Success: 100%

    Multiplier chance: 10% (1.2 - 1.0) × 50%

Possible outcomes:
Outcome	Probability	Inputs	Outputs
Normal (×1)	90%	3 Ore	2 Common Metal
Multiplier (×2)	10%	6 Ore	4 Common Metal
Example 3: Make Simple Tools (Simple Manufacturing: 0.8):

    Success: 80% chance of success (20% failure)

    Multiplier chance: 0% (rating < 1.0)

Possible outcomes:
Outcome	Probability	Inputs	Outputs
Success (×1)	80%	2 Common Metal	1 Tool
Failure	20%	2 Common Metal lost	None
Advantages of This Approach:

    Simpler scaling: Adding new processes becomes easy—just link to existing skills.

    Intuitive actor development: Actors naturally specialize and diversify over time.

    Realistic: Reflects real-world skill transfer between related processes