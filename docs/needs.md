# Actor Needs (Drives)

Actor needs are drives in `spacesim2/core/drives/`. Each drive inherits from
`ActorDrive` (`actor_drive.py`), is attached to one actor, and ticks once per
turn: it consumes satisfying goods from the actor's inventory and updates a
`DriveMetrics` record.

| Drive | Consumption | Basic good | Quality good | Miss penalty |
|-------|-------------|------------|--------------|--------------|
| Food (`food_drive.py`) | deterministic, 1/turn | `food` | `processed_food` | 0.2 |
| Clothing (`clothing_drive.py`) | stochastic, p = 1/60 per turn | `clothing` | `quality_clothing` | 0.5 |
| Shelter (`shelter_drive.py`) | stochastic, p = 1/120 per turn | `simple_building_materials` | `prefab_housing` | 0.5 |
| Health (`health_drive.py`) | stochastic, p = 1/90 per turn | `medicine` | `advanced_medicine` | 0.4 |

## Metrics

Each `tick()` updates four values, all in [0, 1]:

- **health**: 1.0 if the drive's material is in stock (for food, whether the
  actor ate this turn), else 0.0.
- **debt**: accumulated neglect. A missed consumption event adds the drive's
  `DEBT_MISS_PENALTY`. A satisfied turn multiplies debt by
  `DEBT_DECAY_FACTOR` (0.8), or by `QUALITY_DEBT_DECAY_FACTOR` (0.5) when the
  quality good was consumed. Stochastic drives decay only on event turns or
  while stocked. `get_score()` is `1 - debt`.
- **buffer**: expected days of supply (stock / expected events per day)
  through `log_norm_ratio(days, target, cap)`, so returns diminish toward
  a per-drive target. Target/cap days: food 7/30, clothing 60/180,
  health 90/270, shelter 120/360.
- **urgency**: priority multiplier. Fixed at 1.0 for all drives.

## Quality tiers

Every drive tries its quality good first and falls back to the basic good.
Quality consumption decays debt faster (0.5 vs 0.8). Both tiers count toward
buffer coverage. The basic good is the one that trades in volume.

## Economic coupling (willingness to pay)

`ActorDrive` exposes the hooks brains use to price buy orders:

- `deprivation_stake()`: welfare value of one consumed unit. Equals the
  drive's `MISS_PENALTY`, so it is comparable across drives.
- `marginal_welfare()`: `deprivation_stake() * (1 - buffer)`. A well-stocked
  drive values an extra unit less.
- `materials()`: satisfying commodities, basic good first.
- `target_units()`: inventory level the actor keeps on hand
  (food 6, clothing 3, shelter 3, health 2).

## Adding a new drive

A drive needs a complete supply chain or it starves silently:

1. Add the raw material and finished good to `data/commodities.yaml`, and
   gathering and production processes to `data/processes.yaml`. Use the
   `commodity-process-design` skill.
2. Create the drive class in `core/drives/` inheriting `ActorDrive`. Follow
   `clothing_drive.py` for stochastic durable goods or `food_drive.py` for
   deterministic staples. Raise `ValueError` in `__init__` if the required
   commodity is missing from the registry.
3. Wire it into actor construction and check that brains trade the new
   commodities. Brains iterate commodities dynamically; do not hardcode.

## Not implemented

Money-savings, tool-ownership, and social or variety needs have no drive
classes. Money and tools are handled directly by brain logic.
