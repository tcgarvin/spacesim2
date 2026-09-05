# Actor Needs (Drives)

Actor needs are drives in `spacesim2/core/drives/`. Each drive inherits from
`ActorDrive` (`actor_drive.py`), is attached to one actor, and ticks once per
turn: it consumes satisfying goods from the actor's inventory and updates a
`DriveMetrics` record.

| Drive | Consumption | Basic good | Fallback good | Miss penalty |
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

## Fallback goods

Every need drive consumes its basic good first and the fallback good only
when the basic good is out of stock. Fallback consumption decays debt faster
(0.5 vs 0.8). Both goods count toward buffer coverage, but `materials()`
returns the basic good only, so a need never bids for or stockpiles the
upgraded good. The upgraded goods are owned by the prosperity drives below.

## Prosperity drives

`prosperity_drive.py` holds one class, `ProsperityDrive`, with one instance
per category on every regular actor. Design in `docs/prosperity-design.md`.

| Category | Good | Base event rate | Base target units |
|----------|------|-----------------|-------------------|
| food | `processed_food` | 1/3 per turn | 3 |
| clothing | `quality_clothing` | 1/60 | 2 |
| shelter | `prefab_housing` | 1/120 | 2 |
| health | `advanced_medicine` | 1/90 | 1 |
| luxury | `luxury_goods` | 1/45 | 2 |
| computing | `computers` | 1/180 | 1 |

- `WELLBEING = False`: excluded from planet wellbeing, the summary `drives`
  block, and the verdict. Reported in the summary `prosperity` block.
- Miss penalty 0.1, below every need, and `ActorBrain._drives_by_priority`
  ranks prosperity drives behind all needs regardless of welfare.
- Gate: `can_purchase()` is true only while every need drive has
  `debt < 0.25` and `buffer >= 0.3` (`needs_are_met`). Consumption from stock
  and metric updates continue while gated.
- Taste: `Actor.tastes` is fixed at creation, weight 1.0 per category and
  3.0 on one favorite. It multiplies the event rate and the target stock.
  Nothing else reads it.
- `coverage` is an EMA of "event served" with a 60-turn half-life;
  `prosperity_index(actor)` is its unweighted mean across categories.

## Economic coupling (willingness to pay)

`ActorDrive` exposes the hooks brains use to price buy orders:

- `deprivation_stake()`: welfare value of one consumed unit. Equals the
  drive's `MISS_PENALTY`, so it is comparable across drives.
- `marginal_welfare()`: `deprivation_stake() * (1 - buffer)`. A well-stocked
  drive values an extra unit less.
- `materials()`: satisfying commodities, basic good first.
- `target_units()`: inventory level the actor keeps on hand
  (food 6, clothing 3, shelter 3, health 2).
- `can_purchase(actor)`: whether the brain may bid for this drive this
  turn. Always true for needs; prosperity drives gate on met needs.

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
classes. Money and tools are handled directly by brain logic. Habituation
(a standard of living that creates debt when lost) is deferred.
