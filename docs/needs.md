# Actor Needs (Drives)

Actor needs are modeled as **drives** in `spacesim2/core/drives/`. Each drive
inherits from `ActorDrive` (`actor_drive.py`), is attached to an actor
(drives have memory), and is ticked once per turn: it consumes satisfying
goods from the actor's inventory and updates a `DriveMetrics` record.

Four drives exist:

| Drive | Consumption | Basic good | Quality good | Miss penalty |
|-------|-------------|------------|--------------|--------------|
| Food (`food_drive.py`) | deterministic, 1/turn | `food` | `processed_food` | 0.2 |
| Clothing (`clothing_drive.py`) | stochastic, p = 1/60 per turn | `clothing` | `quality_clothing` | 0.5 |
| Shelter (`shelter_drive.py`) | stochastic, p = 1/120 per turn | `simple_building_materials` | `prefab_housing` | 0.5 |
| Health (`health_drive.py`) | stochastic, p = 1/90 per turn | `medicine` | `advanced_medicine` | 0.4 |

## The metric model (all values in [0, 1])

Each `tick()` updates four metrics:

- **health** — immediate status: 1.0 if the drive's material is in stock (for
  food: whether the actor ate this turn), else 0.0.
- **debt** — accumulated neglect. On a missed consumption event debt gains
  the drive's `DEBT_MISS_PENALTY`; on satisfied turns it decays by
  `DEBT_DECAY_FACTOR` (0.8), or faster (`0.5`) when the *quality* good was
  consumed. Stochastic drives decay only while stocked (or on event turns).
  The drive's overall score (`get_score()`) is `1 - debt`.
- **buffer** — log-normalized inventory coverage: expected days of supply
  (stock / expected events per day) mapped through
  `log_norm_ratio(days, target, cap)` — diminishing returns toward a
  per-drive target (e.g. food pantry target 7 days, cap 30; shelter 120/360).
- **urgency** — context-dependent priority multiplier (currently fixed 1.0
  for all drives).

## Quality tiers

Every drive tries its quality good first and falls back to the basic good.
Quality consumption halves debt faster (decay 0.5 vs 0.8); both tiers count
toward buffer coverage. The basic good is the workhorse that actually trades.

## Economic coupling (willingness to pay)

`ActorDrive` exposes the hooks brains use to price buy orders:

- `deprivation_stake()` — welfare value of one consumed unit; equals the
  drive's `MISS_PENALTY`, comparable across drives because all drives measure
  welfare in the same avoided-debt currency.
- `marginal_welfare()` — `deprivation_stake() * (1 - buffer)`: a well-stocked
  drive values an extra unit less.
- `materials()` — satisfying commodities, basic (market) good first.
- `target_units()` — inventory level the actor aims to keep on hand
  (food 6, clothing 3, shelter 3, health 2).

## Adding a new drive

A drive needs a complete supply chain or it will starve silently:

1. Add the raw material and finished good to `data/commodities.yaml`, and
   gathering + production processes to `data/processes.yaml` (use the
   `commodity-process-design` skill).
2. Create the drive class in `core/drives/` inheriting `ActorDrive`; follow
   the stochastic pattern in `clothing_drive.py` for durable goods or the
   deterministic pattern in `food_drive.py` for staples. Raise `ValueError`
   in `__init__` if the required commodity is missing from the registry.
3. Wire it into actor construction and verify brains trade the new
   commodities (brains iterate commodities dynamically — avoid hardcoding).

## Future ideas (not implemented)

Earlier designs sketched money-savings, tool-ownership, and social/variety
needs as scored utilities. None have drive classes; money and tools are
handled directly by brain logic, and social/luxury needs remain an open
design idea.
