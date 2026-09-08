# Actor Needs (Drives)

Actor needs are drives in `spacesim2/core/drives/`. Each drive inherits from
`ActorDrive` (`actor_drive.py`), is attached to one actor, and ticks once per
turn: it consumes satisfying goods from the actor's inventory and updates a
`DriveMetrics` record.

| Drive | Consumption | Basic good | Fallback good | Miss penalty |
|-------|-------------|------------|--------------|--------------|
| Food (`food_drive.py`) | deterministic, 1/turn | `processed_food` | `food` | 0.2 |
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
(0.5 vs 0.8). Both goods count toward buffer coverage. For clothing,
shelter and health `materials()` returns the basic good only, so those needs
never bid for or stockpile the upgraded good; the upgraded goods are owned
by the prosperity drives below. Food is the exception: `FoodDrive` bids for
both the staple `processed_food` and the premium `food`.

## Prosperity drives

`prosperity_drive.py` holds one class, `ProsperityDrive`, with one instance
per category on every regular actor. Design in `docs/prosperity-design.md`.

| Category | Good | Base event rate | Base target units |
|----------|------|-----------------|-------------------|
| food | `food` | 1/60 | 2 |
| clothing | `quality_clothing` | 1/60 | 2 |
| shelter | `prefab_housing` | 1/120 | 2 |
| health | `advanced_medicine` | 1/90 | 1 |
| luxury | `luxury_goods` | 1/45 | 2 |
| computing | `computers` | 1/180 | 1 |

`processed_food` comes from `process_food`: 40 biomass + 1 chemicals -> 60
processed_food at a chemical plant. Hand-cooked `food` comes from
`make_food`: 4 biomass -> 4 food, no facility. Food is the one category
whose prosperity good is also a need material: `FoodDrive.materials()`
returns both goods and bids for whichever is cheaper.

- `WELLBEING = False`: excluded from planet wellbeing, the summary `drives`
  block, and the verdict. Reported in the summary `prosperity` block.
- Miss penalty 0.1, below every need, and `ActorBrain._drives_by_priority`
  ranks prosperity drives behind all needs regardless of welfare.
- Gate: `can_purchase()` is true only while every need drive has
  `debt < 0.25` and `buffer >= 0.2` (`needs_are_met`). Consumption from stock
  and metric updates continue while gated.
- Taste: `Actor.tastes` is fixed at creation, weight 1.0 per category and
  3.0 on one favorite. It multiplies the event rate and the target stock.
  Prosperity drives read it at construction; the actor also keeps it for
  later export and UI use, not yet consumed by either.
- `coverage` is an EMA of "event served" with a 60-turn half-life;
  `prosperity_index(actor)` is its unweighted mean across categories.

## Economic coupling (willingness to pay)

`ActorDrive` exposes the hooks brains use to price buy orders:

- `deprivation_stake()`: welfare value of one consumed unit. Equals the
  drive's `MISS_PENALTY`, so it is comparable across drives.
- `marginal_welfare()`: `deprivation_stake() * (1 - buffer)`. A well-stocked
  drive values an extra unit less.
- `materials()`: satisfying commodities; need drives return only the basic
  good, prosperity drives return their own upgraded good.
- `target_units()`: inventory level the actor keeps on hand
  (food 6, clothing 3, shelter 3, health 2).
- `can_purchase(actor)`: whether the brain may bid for this drive this
  turn. Always true for needs; prosperity drives gate on met needs.

### Substitute bids for a drive's other materials

`ActorBrain._drive_buy_commands` bids for the cheapest material that has a
local ask, so the drive's other materials draw no bid at all. Ships plan
against the destination order book, so a planet whose colonists hand-feed on
`food` at 7 shows no demand for `processed_food`, even though every one of
them would take it at 6. Where a local plant sells a few units at 20, the
book showed five bids at 18 and nothing under it, and no ship could sell a
full hold there. The staple surplus stayed on the plant planets at 1.

`ActorBrain._add_substitute_material_bids` posts one extra bid per other
material of the drive, whether or not someone sells it locally at a higher
price:

| Term | Value |
|------|-------|
| price | `min(wtp, ask * SUBSTITUTE_BID_DISCOUNT, reference * (1 + scarcity_pressure))` |
| quantity | the drive's restock `need`, capped by the money left |
| when | after every drive has placed its primary bid |

`wtp` is `_drive_willingness_to_pay` for the drive, unchanged. `ask` is the
cheapest local ask among the drive's materials and `SUBSTITUTE_BID_DISCOUNT`
is 0.9, so the buyer offers a little less for the untried good than for the
one on the shelf. `reference` is `_drive_bid_reference`, and unfilled bids
raise `scarcity_pressure` toward its cap of 3.0, so a never-traded good's
bid starts where the market can supply and ratchets up while nothing
arrives. With a shelf ask present the discounted ask is the binding term.

The pass runs last, after every drive's primary bid, and draws on the same
running budget. A substitute bid therefore never outbids a shelf purchase
for a lower-priority need, and the bids an actor places in a turn together
reserve no more than its money. Quantity is the full restock `need`, so an
actor with cash can end a turn holding up to twice its target; consumption
keeps it out of the market until stock falls back below target.

Only `FoodDrive` lists more than one material, so today only
`processed_food` is affected. Cost is one dict lookup per material:
`_cheapest_material_ask` has already filled the quote cache.

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
