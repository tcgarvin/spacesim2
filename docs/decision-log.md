# Decision Log

Append-only record of closed decisions, postmortems, and landed campaigns.
Newest first. Open work lives in `TODO.md`; current reference docs live
alongside this file.

## 2026-09-07 - Substitute bids for the staple; why processed food still does not ship

Question: after the tank split, does cheap `processed_food` move from plant
planets to poor planets? No. In a 600-turn 100-planet run ships bought 24
units in the last 100 turns against 320,994 traded locally, with the staple
at 1.0 on plant planets and 19 one lane away. Food health is above 0.99 on
every planet; poor planets hand-feed at 6.7 instead of importing.

Change: `ActorBrain._add_substitute_material_bids` (was
`_add_absent_material_bids`) now bids for a drive's other materials whether
or not someone sells them locally, at `min(wtp, ask *
SUBSTITUTE_BID_DISCOUNT, reference * (1 + pressure))` with the discount at
0.9. Before, a single local staple ask above the food price silenced every
hand-feeding actor's staple bid, so the destination book showed five bids
at 18 and nothing under them. 12-planet A/B (3 reps x 300 turns) neutral on
every KPI.

100-planet before/after, 400 turns, last 100 turns:

| KPI | before (`run_20260907_182849`, t500-600) | after (`run_20260907_200044`) |
|---|---|---|
| planets with staple best bid >= 3 | 36 | 59 |
| mean resting staple bids on those | 31 | 45 |
| staple units bought by ships | 24 | 10 |

The book got deeper and nothing shipped. `notebooks/processed_food_export_pairs.py`
replays the planner per (origin, destination) pair, 15,383 pairs:

| pair outcome | share |
|---|---|
| fuel not buyable at origin | 49% |
| no money for trading after round-trip fuel, refuel floor, maintenance | 43% |
| plan built, margin below 0.15 | 6% |
| no sellable demand | 2% |
| plan accepted | 0.3% (40) |

Evaluator ships hold median 372 credits and 1 unit of fuel against a median
26-unit round trip at 39 per unit. Where a plan is built, the walked
destination depth sits at 3-6 (the discounted food price; only 325 of
about 3,000 units at 15) against an origin entry of 2-4, so a 66-unit load
grosses 330 against 168 fuel and 42 maintenance. The 40 accepted plans are
all one hop, median profit 98, and lose the absolute-profit ranking to
tools and clothing at a median 1,264. Ships do carry bulk cheap goods when
the spread is there: 13,053 units of biomass over the run.

Conclusion: demand depth was not the blocker. The staple's shippable
spread is 1-3 credits per unit, which pays for one hop and no more, and
92% of pair evaluations fail on fuel or cash before price matters. The
next levers are fleet fuel and cash at plant planets, then plan ranking.
`notebooks/staple_flow.py` is the quick check.

## 2026-09-07 - Fuel tank split from the hold, bigger tank, add-on cargo

Ships bought fuel at spike prices and it was the fleet's whole loss: over
600 turns at 100 planets the fleet spent 673k on fuel against 350k gross
cargo margin, 55% of fuel credits went above 1.3x the galaxy reference, and
the premium over reference was 266k. An in-process probe
(`notebooks/ship_fuel_path_probe.py`) attributed the spiked fills by code
path: the survival top-up ration branch 252k, plan fuel 34k, maintenance
18k, standing bids 7k. Adopted plans mostly survived honest costing (34 of
152 spiked-origin plans fail a 15% margin with the return leg charged at
the local ask), so `TradePlan` was not the lever. Spikes were local: at
spike-buy turns 32 of 40 ask planets were within 1.3x of reference.

Three changes in `core/ship.py`:

- `Ship.fuel` is a tank separate from the hold. Hold fuel is ordinary
  cargo; `Ship.pump_fuel` moves fills into the tank each docked turn,
  keeping `ShipBrain.fuel_cargo_to_keep()` for a fuel run's load. Removed:
  `_fuel_delivery_in_progress`, `_local_fuel_bid_is_scarcity_priced`,
  `_committed_fuel_floor`, the distress tank liquidation, and every
  hold-room bound on fuel buys. `_sellable_quantity` is the hold count.
- Tank sized to `FUEL_CAPACITY_ROUND_TRIP_HEADROOM` 3.0 mean round trips
  (was 1.5), `BASE_FUEL_CAPACITY` 60 (was 50), so bunkering where fuel is
  cheap covers several trips.
- Add-on cargo: `_place_addon_bids` fills the hold left over after the
  plan's bid with up to `ADDON_MAX_COMMODITIES` other goods the destination
  bids for, judged on revenue minus purchase cost. Probe: hold 21% full at
  the median departure, add-on available at 84% of departures, worth 34% of
  planned profit in total.

12-planet 200-turn A/B, 3 reps per arm (`tmp/ab_tank12`): every drive,
money and prosperity KPI neutral; departures 24 -> 17 and idle ships 4 ->
5.7 with delivered units flat (86 -> 88), consistent with fewer, fuller
trips. Fuel geography does not bind at 12 planets.

100 planets, one 400-turn run each, before (`run_20260907_142956`, turns
0-399) and after (`run_20260907_163218`):

| KPI (last 50 turns) | before | after |
|---|---|---|
| ship-delivered units | 131 | 371 |
| departures | 51 | 231 |
| stranded ships | 41 | 27 |
| idle ships | 65 | 32 |
| cargo gross margin, turns 0-399 | 223k | 326k |
| fleet fuel spend, turns 0-399 | 599k | 727k |
| spike premium over reference, turns 0-399 | 237k | 362k |

Mobility and trade roughly tripled and the rescue-bid channel shrank
(ship-to-ship spiked fills 118k -> 51k credits, 15x -> 5.9x reference), but
total spiked fuel spend rose with the trip count: industrialist asks at
about 4x reference sold ships 1271 units for 347k. The tank lets a ship
skip a spiked market; nothing yet makes it do so. The price discipline on
the survival top-up and the plan fuel step is the open item in `TODO.md`.

## 2026-09-07 - Fleet fuel sell-off: value the tank, not the cheapest ask

The fleet sold its starting tanks in the launch window and re-bought the
same fuel at spike prices. `_local_fuel_bid_is_scarcity_priced` anchored on
`Navigator.cheapest_fuel_ask()`, the galaxy minimum, and
`_place_flow_sell_orders` rested a fuel remainder at
`max(1, best_bid or avg or 1)`, which is 1 credit on a planet that has never
traded fuel. That 1-credit ask pinned the minimum at 1, so every local fuel
bid cleared the gate for every ship. The two defects fed each other: the same
1-credit asks were the believable producer asks, so the value reference read
1-2 credits for the first 30 turns.

Fix, both layers in `core/ship.py`:

- The gate compares the local bid against `_fuel_value_reference()`, the
  median believable per-planet valuation, marked up by `FUEL_BID_MARGIN`
  (30%, unchanged). No believable valuation anywhere, the turn-0 state,
  closes the gate; it used to fall back to `FUEL_BID_FALLBACK_FLOOR`.
- `_sell_floor_price` floors `nova_fuel` asks at `ceil(reference)`, or
  `FUEL_BID_FALLBACK_FLOOR` (15) before anything has traded, applied to both
  the bid-level asks and the resting remainder. Other cargo is unfloored.

Probe, `notebooks/fleet_fuel_launch_probe.py`, 100 planets, 120 turns, one
run each:

| metric | before | after |
|--------|--------|-------|
| ship fuel sell orders / units | 1197 / 5218 | 134 / 287 |
| sells passing the scarcity gate | 100% | 76% |
| sells while distressed | 1% | 17% |
| median sell ask | 15 | 2543 |
| median money t70 / t120 | 1671 / 1557 | 4537 / 2477 |
| median tank fuel t70 / t120 | 2 / 2 | 4 / 3 |
| median fuel buy price | 164 | 171 |
| median value reference, first 30 turns | 1-2 | no fuel orders placed |

The remaining sells are what the gate was meant to allow: a sixth of them
are a distressed ship converting tank fuel to cash, and the rest are rescue
bids that beat the reference. The high median sell ask is the floor tracking
a spiky reference across 134 orders, not a price the fleet pays.

12 planets, 200 turns: PASS. Fuel purchase price did not move; the win is
that ships keep their tanks and their money.

## 2026-09-07 - Staple demand bid: bid for a drive material nobody sells here

Importer planets never posted a `processed_food` bid, so 1.9M units of
staple sat on the plant planets at 1-2 credits and no ship ever loaded
one. `ActorBrain._drive_buy_commands` bids for the cheapest drive material
that has a *local ask*; a biomass-poor planet with no plant sees only hand
`food` for sale and bids 11-19 for that. Ships plan against the
destination order book, so the demand was invisible off-world.

Decision: after every drive has placed its primary bid,
`ActorBrain._add_absent_material_bids` posts one more bid per drive
material with no live local ask, at
`min(wtp, ask, reference * (1 + scarcity_pressure))` for the drive's
restock `need`. No hardcoded commodity: it iterates `materials()`, and
only `FoodDrive` lists two, so today it fires only for `processed_food`.

- `wtp` is the unchanged `_drive_willingness_to_pay`; `ask` is the
  cheapest local ask across the drive's materials, so nobody pays more for
  an absent good than for the substitute on the shelf; unfilled bids raise
  `scarcity_pressure` toward 3.0, so the bid ratchets from a level the
  market can supply up to the ceiling.
- The pass runs last and shares the caller's running budget. Placing it
  inside the per-drive loop instead cost shelter 0.82 -> 0.70 across two
  reps and flagged the verdict WARN: food is first in
  `_drives_by_priority`, so a second food bid claimed budget ahead of
  shelter's first. Running it after all primary bids removed the drift.
- Cost is one dict lookup per material; `_cheapest_material_ask` has
  already filled the quote cache for that turn.

`notebooks/processed_food_export_probe.py`, 100 planets, 300 turns,
sampled every 50 from turn 150, surplus threshold 300, one rep each arm.
The probe gained a `dest_bid_depth` field for this.

| processed_food, median over 56/58 surplus-planet observations | before | after |
|---|---|---|
| destination bid depth (units) | 29 | 1007 |
| sellable quantity of the best plan | 1 | 9 |
| destination best bid | 15 | 16 |
| expected sell price | 15 | 6.5 |
| gate `pair_infeasible_fuel_or_cash` | 93% | 91% |
| gate `no_dest_demand_or_budget` | 0% | 2% |
| staple stock held at a surplus planet | 5392 | 3913 |

The fleet is broke in both arms, so `pair_infeasible_fuel_or_cash` still
blocks 9 in 10 evaluations and ships hauled 0 units of staple either way;
that fix is separate. What moved is the demand side: a ship that can reach
a destination now finds about a thousand units bid for instead of thirty.

12 planets, 200 turns, 3 reps each arm, against d5758f6:

| kpi | before | after |
|-----|--------|-------|
| verdict | PASS, PASS, WARN | WARN, PASS, PASS |
| drives.food.mean_health | 0.998 ± 0.001 | 0.999 ± 0.000 |
| drives.clothing.mean_health | 0.795 ± 0.193 | 0.858 ± 0.053 |
| drives.shelter.mean_health | 0.712 ± 0.186 | 0.728 ± 0.052 |
| drives.health.mean_health | 0.244 ± 0.157 | 0.423 ± 0.117 |
| prices.food | 6.5 ± 0.4 | 5.3 ± 0.7 |
| money.mean | 597 ± 30 | 567 ± 54 |

No KPI drifts down beyond the ±0.05 the population means are stable to.
The WARN in each arm is the same 12-planet flakiness, shelter below 0.70.

Open: hand `food`'s median best-plan quantity fell 76 -> 8.5 in the same
probe on 5 feasible observations either side, which is too small a sample
to call. Worth rechecking once the fleet can move.

## 2026-09-07 - Food refresh: two tracks, facility upkeep, heavy machinery

After 6e82e07 removed the free food from the skill multiplier, honest food
cost more than a planet's whole labor: gather 4 biomass x attribute per
turn and 4 biomass -> 2 food, against 1 food per actor per turn, is 0.5(1 +
1/a) labor-turns per meal, 133% of labor at the median attribute 0.6. A
300-turn 12-planet run on 6e82e07 verdicted FAIL with money mean 151 and
health drive 0.00. The old equilibrium had run on the bug.

Decision: two tracks with a chosen labor share, about 46% of labor for
food at the median planet on the hand track and about 8% on the
industrial track. Design page: the "Two-Track Food Chain" artifact.

| Process | Requires | Inputs | Outputs | Labor |
|---------|----------|--------|---------|-------|
| gather_biomass | nothing | none | 8 biomass x a | 1 |
| make_food | nothing | 4 biomass | 4 food | 1 |
| farm_biomass | farm, simple_tools, upkeep heavy_machinery 0.01 | 1 chemicals | 64 biomass x a | 1 |
| process_food | chemical_plant, upkeep heavy_machinery 0.01 | 40 biomass, 1 chemicals | 60 processed_food | 1 |
| make_heavy_machinery | metalworking_facility, simple_tools | 5 common_metal | 1 heavy_machinery | 3 |
| build_farm | simple_tools | 5 building materials, 1 heavy_machinery | farm | 5 |
| build_chemical_plant | simple_tools | 5 building materials, 2 common_metal, 1 heavy_machinery | chemical_plant | 5 |

Choices, and why:

- Heavy machinery is consumed as facility upkeep, not carried as a tool.
  A process may declare `upkeep: {commodity: probability}`; each run rolls
  it, a hit consumes one unit, and a hit with none on hand fails the run
  without side effects, as a missing tool does. Expected upkeep enters
  recipe cost imputation and the replacement quote, and the industrialist
  keeps one unit of each upkeep good. The expected cost equals a 1% tool
  break; the difference is that machinery demand now recurs per facility,
  and machinery at 175-260 credits is cargo worth hauling where processed
  food at 2 credits is not.
- The plant is a generic `chemical_plant` (no glass in the build), not a
  food-specific facility; the chemistry lab stays separate.
- Plain chemicals, not refined, feed the farm and the plant, so the staple
  chain never waits on glass.
- Chemicals-only gathering was rejected: one unit of chemicals costs 1.5
  biomass plus half a labor-turn, and a 2x boost on hand gathering is a
  loss below attribute 0.45.
- Processed food is the staple `FoodDrive` eats and bids for; hand-cooked
  food is its fallback and the prosperity food good (entry below).
- Landed one layer at a time: 3ac8f3f, 912d065, a5e3755, 637e296, d4be82d,
  afe82f8, each verified with pytest and a 300-turn 12-planet summary.

Found on the way:

- `ActorBrain._get_build_process_for_facility` is a hardcoded map; a
  facility missing from it imputes an infinite recipe cost and is never
  built. `test_every_required_facility_has_a_build_process` now guards it.
- `dev ab` launched the baseline arm without a working directory, and the
  sim loads `data/` relative to the current directory, so the before arm
  ran old code against the working tree's YAML (fixed in c3e57ec). Every
  earlier A/B whose change touched `data/` is suspect.
- Inside a git worktree, `uv run ... spacesim2 run` resolves the package
  through the editable install and executes the primary checkout's code;
  measure on main after merging, or set `PYTHONPATH` to the worktree.
- The flip's health and shelter regression was labor, not the numeraire:
  the prosperity food category kept a factory rate (1/3 per turn, target 3)
  on a good every actor cooks by hand, and food work took 79% of process
  runs. Retuned to 1/60 and target 2 (afe82f8); the probe is
  `notebooks/food_flip_numeraire_probe.py`.

A/B, 12 planets, 300 turns, 3 reps, 6e82e07 vs afe82f8, with the fixed
baseline launch:

| kpi | before | after | verdict |
|-----|--------|-------|---------|
| verdict.status | FAIL,FAIL,FAIL | PASS,PASS,PASS | |
| money.mean | 163 ± 7 | 794 ± 58 | |
| drives.food.mean_health | 0.941 ± 0.014 | 0.999 ± 0.001 | IMPROVE |
| drives.health.mean_health | 0.024 ± 0.027 | 0.680 ± 0.090 | IMPROVE |
| drives.shelter.mean_health | 0.278 ± 0.003 | 0.905 ± 0.053 | IMPROVE |
| drives.clothing.mean_health | 0.388 ± 0.015 | 0.950 ± 0.041 | IMPROVE |
| prosperity.index_mean | 0 | 0.193 ± 0.006 | IMPROVE |
| prosperity.gate_pass_share | 0.010 ± 0.011 | 0.579 ± 0.093 | IMPROVE |
| prosperity.coverage.food | 0 | 0.896 ± 0.002 | IMPROVE |
| trade.ship_delivered_total | 11 ± 15 | 0.3 ± 0.6 | neutral |

Table in `tmp/ab_food_final/table.txt`. A single 600-turn run on 12
planets shows the transition under way: 137 chemical plants and 162 farms,
money mean 1715, prosperity index 0.214, processed food at 2.8 credits;
the health drive at 0.25 (WARN) with medicine at 71 credits and common
metal at 217, since each machinery unit takes five metal.

Open, in `TODO.md`: the transition takes until well past turn 300 (plants
on 2-5 of 12 planets at 300, most planets by 600), metal is the
bottleneck once machinery demand arrives, a plant out-produces its planet
and the surplus is not exported, and the numeraire anchored on the
cheapest food will cut every need drive's credit WTP as the staple settles
near 2-3 credits.

## 2026-09-07 - Food flip: processed food is the staple, hand-cooked food the premium

Layer 3 of the food-system refresh. Layers 1 and 2 made hand food cheap
(`gather_biomass` 8 biomass, `make_food` 4 biomass -> 4 food) and added an
industrial recipe (`process_food`: 40 biomass + 1 chemicals -> 60
processed_food at a chemical plant). Processed food was still a prosperity
good consumed at 1/3 per turn, so it piled up: 54,776 units held at turn
300 on 12 planets.

Decision: swap the two. `FoodDrive` eats and bids for `processed_food`
first and `food` second; the food prosperity category owns `food`. Both
goods are drive materials, so `_cheapest_material_ask` buys whichever is
cheaper and the pantry counts both. Three supporting changes:

- Numeraire. `_value_of_money` and `_surplus_money_discount` anchored on
  `materials()[0]`, which is now the staple. On a planet with no chemical
  plant the staple has no trades and only an imputed price, so lambda would
  be anchored on a good nobody there sells. Both now take the cheapest
  effective price across the drive's materials
  (`ActorBrain._cheapest_effective_price`).
- Willingness-to-pay cap. `_drive_willingness_to_pay` capped a need bid at
  the actor's replacement cost for the target good. For a plant-less actor
  that cost is None for the staple, leaving the bid unbounded. The cap is
  now the cheapest self-supply across the drive's materials, which for that
  actor is cooking by hand.
- Cook-or-gather gates. `ColonistBrain` and `IndustrialistBrain` read the
  `food` quantity alone to decide whether to cook. They now read
  `food_pantry_units`, so an actor living on bought staple stops cooking.
  The hand-cook fallback stands: an empty pantry still gathers and cooks.

The substitute bound (`ProsperityCategory.bound_commodity_id`, reverted in
7711088) is closed by this; the flip is the mechanism that stops processed
food competing with the staple, because it is the staple.

Plant-less planets do not go hungry. At 12 planets, 300 turns, the five
planets with no chemical plant ran food health 0.97-1.00 on hand-cooked
food trading at 3-7 credits, against 1.00 on plant planets.

A/B, 12 planets, 300 turns, 3 reps, against a5e3755 (the facility-upkeep
merge, so the flip is the only difference):

| kpi | before | after | delta | verdict |
|-----|--------|-------|-------|---------|
| verdict.status | PASS,PASS,PASS | PASS,PASS,PASS | | |
| prosperity.coverage.food | 0.344 ± 0.004 | 0.837 ± 0.046 | +0.493 | IMPROVE |
| prosperity.index_mean | 0.075 ± 0.003 | 0.148 ± 0.010 | +0.073 | IMPROVE |
| prosperity.gate_pass_share | 0.602 ± 0.013 | 0.245 ± 0.060 | -0.357 | REGRESS |
| prosperity.coverage.clothing | 0.096 ± 0.015 | 0.047 ± 0.017 | -0.050 | REGRESS |
| drives.food.mean_health | 0.999 ± 0.001 | 0.990 ± 0.003 | -0.008 | REGRESS |
| drives.health.mean_health | 0.686 ± 0.025 | 0.316 ± 0.080 | -0.370 | REGRESS |
| drives.shelter.mean_health | 0.867 ± 0.030 | 0.781 ± 0.015 | -0.087 | REGRESS |
| drives.clothing.mean_health | 0.945 ± 0.030 | 0.882 ± 0.001 | -0.063 | REGRESS |
| money.mean | 828 ± 65 | 851 ± 7 | +23 | |

The prosperity food category is now hand-cooked food eaten at 1/3 per turn
on top of the daily staple meal, so every actor has a new standing demand
for labor-intensive food. Prosperity coverage of it goes to 0.84 and the
index nearly doubles, but the labor comes out of the slower chains: health
loses 0.37, shelter 0.09, clothing 0.06, and the prosperity gate passes
less than half as often. Every run still verdicts PASS and food health
stays at 0.99. The right follow-up is the food category's event rate and
target, which were set when the category good was factory-made processed
food at 1/3 per turn; hand food at that rate is a much larger claim on
labor.

An earlier 3-rep A/B against 912d065 read health as neutral (-0.248 with a
0.18 spread), but that baseline predates the facility-upkeep merge and so
mixed two changes. The table above is the isolated one.

The staple glut has not cleared: 50,777 units at turn 300, concentrated on
plant planets (one held 16,990). Processed food clears at 2.1 credits
against hand food at 5.8, so the industrial recipe is far cheaper per unit
than any plant can sell.

## 2026-09-06 - Prosperity demand: surplus money discount, substitute bound on processed food

Four of six prosperity goods never traded. The probe
(`notebooks/prosperity_blockers_probe.py`) put the cause on the demand
side: prosperity willingness-to-pay was welfare-bound at about four times
the food price (~43 credits) for every actor however rich, because the
food-security floor on lambda is fixed and the prosperity stake (0.1) is
half the food stake (0.2). Prefab housing, luxury goods, advanced medicine,
and computers cost 66-285 to make. Gated actors held a median 920 credits.

Decision: phase 4 of `docs/prosperity-design.md`. Prosperity drives price
with lambda scaled by `SURPLUS_REFERENCE_DAYS / affordable_days` beyond 30
days of food money, floored at 0.1 (`ActorBrain._surplus_money_discount`,
f17e74a). Need drives keep the undiscounted lambda. Posted bids stay bounded
by the reference price under scarcity pressure, so the discount raises the
ceiling, not the opening bid.

That moved staple food into processing: rich actors bid processed food up
to ~139, its makers netback-bid food at ~38 against consumers capped at
their own make cost (~17), and missed meals rose 65%, concentrated on
biomass-poor planets where an actor cannot cook its way out
(`notebooks/missed_meal_probe.py`). Two consumer-side fixes were neutral
and were dropped: the industrialist food restock trigger 2 -> 4, and a
1.5x lead-time premium on the make-cost cap when no producing recipe is
executable. The price level was the problem, so processed food, a
nutritional substitute made from food, is bounded at 3x the food price
(`ProsperityCategory.bound_commodity_id`, cd76cf7). The same bound on
prefab housing at 9x building materials was neutral on shelter health and
only cut prefab coverage, so shelter carries no bound. A clipped bid-sweep
valuation for thin goods (b0cb7dd) landed as a correction, neutral on
every KPI.

A/B, 12 planets, 450 turns, cd76cf7 vs 1620630 (4 reps):

| kpi | before | after | verdict |
|-----|--------|-------|---------|
| prosperity.index_mean | 0.146 ± 0.012 | 0.193 ± 0.017 | IMPROVE |
| prosperity.coverage.shelter | 0 | 0.244 ± 0.042 | IMPROVE |
| prosperity.coverage.luxury | 0 | 0.162 ± 0.010 | IMPROVE |
| prosperity.coverage.health | 0 | 0.026 ± 0.003 | IMPROVE |
| prosperity.coverage.computing | 0 | 0.008 ± 0.004 | IMPROVE |
| prosperity.coverage.food | 0.453 ± 0.025 | 0.204 ± 0.029 | REGRESS |
| prosperity.coverage.clothing | 0.426 ± 0.094 | 0.512 ± 0.067 | neutral |
| prosperity.gate_pass_share | 0.697 ± 0.038 | 0.617 ± 0.089 | neutral |
| drives.food.mean_health | 0.940 ± 0.015 | 0.916 ± 0.028 | neutral |
| drives.clothing.mean_health | 0.944 ± 0.022 | 0.907 ± 0.069 | neutral |
| drives.shelter.mean_health | 0.975 ± 0.009 | 0.964 ± 0.018 | neutral |
| drives.health.mean_health | 0.845 ± 0.029 | 0.841 ± 0.045 | neutral |
| money.mean | 1500 ± 70 | 1230 ± 97 | |

Open: shelter need lost ~0.04 health to prefab makers absorbing building
materials on wood-poor planets (`notebooks/substitute_bound_probe.py`);
advanced medicine and computers still cost 2-4x what anyone bids,
electronics being 55-85% of their cost; rare-earth miners never enter
because the ore's own thin price, not the refiner's netback, is what a
miner scores against (`notebooks/rare_earth_chain_probe.py`).

## 2026-09-06 - Recipe inputs bid at netback value, not their own history

An industrialist priced each input off that input's own market: the
cheapest ask, else the 30-day average, else imputed cost times the 1.25
bootstrap margin. The recipe's output never entered the input bid. A
medicine maker on a lab-poor planet could therefore bid 130-145 for
medicine while its bid for refined_chemicals rested at a stale average
below every refiner's 1.2x entry threshold, so the tier below never
started. The same held for the glass needed to build a chemistry lab.
Demand existed one tier up and stopped there.

Decision: procurement bids get the two-layer shape the consumer side
already has in `ActorBrain._drive_buy_commands`.

| Layer | Value |
|-------|-------|
| Ceiling | `(output_value - (recipe_cost - q * unit_c)) / (q * ENTRY_MARGIN)` |
| Posted bid | `min(ceiling, ceil(reference * (1 + scarcity_pressure)))` |

`output_value` is one run's output, from `_recipe_output_value`, factored
out of `_calculate_recipe_score` so entry and procurement price the same
run the same way. `recipe_cost` is `_impute_recipe_cost` for one run,
`unit_c` this actor's imputed unit cost for the input, and `q` its draw
per run: the input quantity, or for a facility build material the build
quantity over the amortization horizon, matching how the build is
charged. Dividing by `ENTRY_MARGIN` (1.2) keeps the recipe
entry-profitable after paying the ceiling. `reference` is the 30-day
average, or imputed cost times the bootstrap margin for a never-traded
good.

A resting ask is still lifted at the ask and is not bounded by the
ceiling; callers rely on taking supply that is already there. When the
output value or the recipe cost cannot be computed there is no ceiling
and the older single-layer pricing applies unchanged, including the
one-shot `_market_is_stalled` premium, so the change is strictly
additive. The ceiling is recomputed every turn from live market state; it
is never carried across turns.

Build tools, which the build needs but does not consume, have no per-run
draw and keep the older pricing.

A build material's ceiling is further capped at `BUILD_INPUT_CEILING_CAP`
(2.0) times its imputed unit cost. Uncapped, the build branch divides a
run's whole margin by a draw of a few bricks over a 150-600 run horizon
and yields ceilings in the hundreds. In the first A/B that let scarcity
pressure carry simple_building_materials from about 25 to 46-110 in most
changed runs, and that good is also the shelter material. Two matches the
most a consumer drive pays over replacement cost at full deprivation.

## 2026-09-05 - Idle ships round 2: fuel geography, distress exit, no self-trades

Done (fb694f9, 903360e, 5cf3eee, 6a4b0be, 5e04fc8). After round 1 the
livelock was gone (local-sale streaks median 68 turns to 2) but half the
fleet still idled by turn 450, now on fuel geography and cash. A cash
ledger showed cargo trading is net positive fleet-wide while fuel bought
above 1.3x the galaxy reference ate three quarters of all fuel spend; the
cash gate was a symptom (median gated ship held 24 credits) and stays.
Changes: the arrival escape reserve is a floor and is never waived on
destination ask depth that may be gone by landing; the survival top-up on
a spiked market buys only the escape leg to the nearest safe seller;
repositioning counts fuel the ship can buy here and funds it through the
same commitment hold-cargo trips use; distressed ships accept any haul
that clears the return-leg fuel and exit distress only above the cash
floor; an actor never trades with itself (maker discovery ladders met at
2, food industrialists sold their pantry and bid it back). The strict
escape floor then proved self-ratcheting (d954064): it applied even when
the destination sells fuel, so a ship funded to exactly its escape leg
could never make the hop to the seller. The floor is now waived only when
the destination shows both a live ask and recent fuel trades, since
recency alone (2026-09-04) and depth alone (this morning) each failed on
their own. 450-turn runs on 100 planets: baseline 71 to 95 idle ships and
8 to 48 departures per window; final main 22 idle and 436 departures in
its first sample, more samples in `tmp/ab_out/`. Left open: an absolute per-unit margin floor (a third of
deliveries realize negative margin, fiber worst) would be a new tunable.

## 2026-09-05 - Idle ships: local-sale veto expires, one-way fuel in margins

Done (8ff2118, 398948e, b096ff3). With operators selling fuel on most
planets, 69/100 ships were still idle by turn 450 while two thirds of them
had a profitable, affordable trade within three lanes. Half of idle time
was a livelock: a ship holding cargo judged destinations on tank fuel
alone (tanks sit near a 9-unit survival target), listed the cargo locally,
and an unconditional "selling locally" veto blocked departure and
replanning forever. The rest was the planner charging round-trip fuel at
spiked local asks into one-way margins. Changes: the veto lasts one turn
unless something filled; reach and fuel commitment use the same departure
requirement the travel gate applies; plan margins charge the outbound leg
(tank fuel at the galaxy reference, bought fuel at the local ask) while
the round-trip cash gate stays; cost basis is the liftable ask, not
max(ask, average); fuel plans load at the origin; ships never bid on their
own asks. Rationing fuel purchases to one leg was tested and rejected (it
grounds the fleet). Single 100-planet runs at turn 300: departures 77 to
217, idle 67 to 39. Full A/B: `tmp/overnight_ab.sh`.

## 2026-09-04 - Spaceport operators: service actors as the fuel counterparty

Landed on main (2678924..96330d2). Two probes on the stranded fleet found
one coordination failure seen from both sides: industrialists held ~22k
fuel listed at an honest ~25 floor with no local buyer above 3, while
every stranded ship posted a rescue bid too small (~7 units) for a fuel
run to beat any other plan. A markdown rule and a carrying cost were both
analyzed and rejected: there was no buyer at any price, and either would
add parameters while destroying the price signal ships use.

Decision: a new kind of actor, the service actor, judged on keeping a
capability available rather than on producing. `ActorType` collapsed to
`REGULAR`/`SERVICE`; market makers became the first service actor
(they had no drives and lived on the wage already, never recorded as a
decision). Spaceport operators are the second: two per planet, a pre-built
`spaceport` facility, one `FacilityUpkeepDrive` whose weighted failure
table lives in the new `data/facilities.yaml`, 50 credits and the wage,
no capital injection, condition decay as the only exit. Shared dealer
logic went to `core/brains/dealer.py` as plain functions; the user
rejected a shared base class. Design: `docs/spaceport-design.md`.

Two post-landing defects, both in the operator's bid rule as specified,
not in the design:
- The bid gate used the galaxy-minimum fuel valuation, pinned at 3-11 by
  one-unit market-maker probe asks, so operators refused every real ask.
  Fixed by bounding bids at the navigator's delivered import price.
- A price ratchet: operators anchored on each other's asks, sellers copy
  the resting bid into their ask, inventory skew added up to 50% per hop;
  fuel went 14 to 94 credits by turn 100 and 7.7k units froze on a
  cost-basis floor. Fixed by anchoring on producer asks only, capping the
  bid at the delivered price, and flooring asks on restock cost the way
  producers floor on replacement cost. The alternative from the original
  design, bidding at imputed make cost, was tested in-process and
  rejected: imputed cost is circular on an operator's planet and it
  bankrupted the fleet.
Also fixed on the way: `dealer.ingest_fills` replayed fills after history
trimming (market makers were exposed), and the ships' fuel value
reference became a median of believable planet valuations instead of a
galaxy minimum that no planet ever passed.

Result at 450 turns, 100 planets (two runs per side, stochastic):
planets with a live fuel ask 24-31 to 68-75; operator fuel stock 6-17 to
5.9-7.3k units sold at ~30; industrialist hoard unchanged (11-20k to
20-23k); nova_fuel mean price 22-31 to 48-52. Fleet activity did NOT
improve: idle ships 65-92 of 100, deliveries in the last 50 turns 32-242
against 220-521. Availability was the design's target and is met; the
fleet is now idle with fuel for sale, which the ratchet probe attributed
to the ship planner's cash gate under higher fuel prices. That is the
next decision, with the industrialist valuation defect (`_output_unit_value`
case 3 values a run at the 30-day average with zero volume) still
deferred. The old stranded-ship KPI is now gamed by ubiquitous asks; judge
on `idle_ships`, `departures_window`, and `ship_delivered_total`.

## 2026-09-03 - Medicine stockpile and fleet lockout: four root causes

Landed on main. Medicine sat in producer inventories (16k units on 16
planets) while a quarter to a third of actors were health-deprived, and
ship-delivered volume fell to zero by turn 400 on the star-lane galaxy.
Four read-only probes, one per suspect, found four separate causes:

1. Consumer WTP ceiling. `_value_of_money` discounted the food numeraire by
   the pantry buffer. Actors keep a six-day pantry by policy against a
   seven-day target, so the buffer sat near 0.3 forever and no good could
   be worth more than ~2.7x the food price (~20). Medicine costs ~29 to
   make. Deprived actors were solvent (median 1,248 credits) and bidding.
   Decision: `FoodDrive.security` adds the days of food an actor could buy
   to the pantry before the same log-normalization; lambda uses it,
   marginal welfare still uses the physical pantry. Deprivation 26% to
   3-5% in isolation.
2. Depth-blind recipe scoring. Output was valued at the top-of-book bid,
   so one-unit market-maker probes at 130-170 read as demand and 156 of
   1,600 actors made medicine against 18 units/turn of consumption.
   Decision: `_output_unit_value` values by liquidity tier: top bid when
   recent volume covers the run, else the bid level whose depth absorbs a
   few runs, else the recent average, and for never-traded goods the bid
   capped at 1.5x imputed cost so cold-start procurement bids still open a
   tier. Producers 330 to 124 at 16 planets.
3. Fleet lockout. `_pair_economics` needs cash for round-trip fuel plus a
   full refuel reserve at origin prices. Ship capital was a constant 1000
   tuned when a trip cost ~90; with longer lane routes and fuel spikes the
   floor passed the stake, every pair returned None, repositioning used
   the same path, and there is no income but cargo, so bankruptcy was
   absorbing. Decision: capital and tank sized from the mean lane round
   trip at setup; the refuel floor charges only the reserve the trip does
   not leave in the tank; a distressed ship may sell tank fuel down to the
   survival target. Rejected: relaxing the round-trip fuel gate, which an
   A/B showed makes deaths worse and pins ships in maintenance.
4. Chain standoff on starved planets. Once a good has any trade history,
   procurement bids rest at the average, which on a cold planet equals
   the imputed make cost, so `make_chemicals` scores exactly zero against
   the 1.2x entry margin and the tiers above it can never execute. Forty
   of fifty local industrialists idled on a positive-scoring recipe they
   could not run. Decision: procurement bids escalate by the bootstrap
   premium when there is no ask, scarcity pressure is high and recent
   volume is near zero; a recipe that fails to execute for 20 turns with
   no movement in its inputs is dropped and put on a 50-turn cooldown.
   Starved planets 3.3 to 0.3 per run, deprivation 20% to 6%, prices flat.

Also landed: the summary verdict gained turn-gated per-drive thresholds,
a `markets` liveness section and a `trade` section for ship-delivered
volume, since none of the above would have failed the old food-only gate.
The health KPI `mean_health` is a possession indicator (fraction holding
any medicine), not a graded score.

## 2026-09-02 - Live UI: simulation moved off the render thread

Landed on branch `spiral-galaxy-star-lanes`. At 100 planets `run_turn` ran
inline in `Director.update` on the render thread and took longer than the
1 turn/s pacing, so the catch-up loop ran several turns per frame and the
UI froze for seconds. A paused frame also re-swept every actor's drives
for wellbeing twice per frame.

Decision: a thin protocol, not a whole-sim snapshot. A `SimulationWorker`
thread owns the sim and publishes one immutable `TurnFrame` per turn
boundary, sized to what the screen shows. Drill-down detail rides along
only for subscribed entities. The director paces turn requests with no
catch-up debt and interpolates ships between frames. The wellbeing sweep
runs once per turn and is shared with the history recorder. The render
thread never reads core objects; a test pins this by stubbing the sim out
after a frame is built. The GIL means a running turn still steals render
time; smoothness at this scale needs a faster sim (`docs/performance.md`).

## 2026-09-01 - Exact-caching passes on the serial path

Landed on main. Three passes replaced repeated scans with caches that
return what a fresh computation would (the current design is described in
`docs/performance.md`): finer `BrainCache` invalidation groups, a ranked
colonist scan, per-turn trade-history memos, a float stdev in
`get_30_day_standard_deviation`, the `replacement_quote_parts` split,
lazy order cancels, order-event gating on logged actors, precomputed
process-definition tuples, and a shared per-market process quote table
keyed on `(turn, quote_version)`. The first pass gained about 1.2x on the
P=40 bench; each later pass gained 1-7% serial at target scale and did not
regress under threads.

Rejected: sharing quote-derived valuations across actors per
`(planet, turn)`. Order posting is immediate and only matching is
deferred, so the shared snapshot would freeze mid-phase book moves. The
user wants actor-specific valuation intact.

## 2026-09-01 - Spike: spiral galaxy with star lanes replaces the open plane

Landed on branch `spiral-galaxy-star-lanes`. Planets were scattered on a
square with straight-line travel between every pair. Now `core/galaxy.py`
places them on a log-spiral and builds a connected planar lane graph
(Delaunay, then Kruskal MST, then a Gabriel-graph filter sampled at
`lane_density`). `Navigator` is the single seam: it runs all-pairs
Dijkstra over the lanes, so every brain that asks for distance gets route
length with no per-brain change, and it raises if the network is ever
disconnected. Ships fuel the whole route at departure and fly past
intermediate planets; per-hop docking is out of scope. Default galaxy size
rose from 5 to 100 planets for `run` and `ui`; `dev check` stays at 5.
5-planet KPIs were unchanged within noise. `galaxy.json` is exported
alongside `planet_attributes.json`.

## 2026-08-31 - Perf campaign: scaling toward 500 planets

Landed across two waves; target scale went from 45+ s/turn to about 3.2.

- Wave 1 (aaf9350): cached market quotes, identity-hashed commodities,
  memoized brain math. C/Rust rewrite rejected.
- Wave 2 (e6c6ddb..2800f43): navigation module with shared distance/fuel
  caches, bounded market and logger memory, incremental best quotes,
  whole-turn `BrainCache` and producer index, single-pass exporter,
  per-turn trade-signal index.
- Order-churn pruning (1867675): two thirds of cancels were identical
  same-turn reposts, so the no-op pairs are dropped. Kept orders must be
  re-timestamped, or stable quotes gain permanent price-time priority over
  drifting drive bids.
- Threaded actor phase (dccfa12, `--workers N`): plain threads over
  per-planet shards on free-threaded CPython 3.14t, no single-thread
  penalty.
- Rejected: fork-per-turn worker pool (parked branch `parallel-actor-phase`
  at 227cba5). Parent-side apply and serialization cost are structural.
  Findings that survive: brains carry cross-turn decision state; macro
  behavior is sensitive to inventory-dict iteration order; per-planet
  sharding needs a planet-coverage invariant.
- Later ruled out as thread-scaling causes: the global `random` lock and
  refcount traffic on shared definitions. See `docs/performance.md`.

## 2026-08-31 - Flow-based ship trading

Landed (993f8f7). Ships traded only the residual order book. With deferred
matching, resting orders are what the local auction rejected, so almost no
candidate plan survived the gates, execution bought top-of-book only, and
loads were dumped into probe bids. Fix: `TraderBrain` plans on recent
clearing prices and volume, bids into the auction at plan price,
accumulates cargo over several docked turns, and sells at bid levels. The
fuel economy became viable and ships ran ore arbitrage unprompted, so
demand propagation emerged through trade with no extra plumbing. Residuals
in `TODO.md`.

## 2026-08-31 - Analysis tooling pruned to the Tier-0/1 loop

Marimo-era Tier-2 tooling removed (a3811c0). The live loop is `--summary`
plus `dev analyze` probe scripts; `notebooks/analysis_template.py` is the
only remaining dashboard. `scripts/` and `dev-tools/` were removed.

## 2026-08-30 - Refiner mis-siting fixed: impute extraction at expected yield

Fixed (c0036fc). The make-branch of `_imputed_unit_cost`
(`core/actor_brain.py`) priced extraction recipes at nominal yield and
ignored `resource_attribute`, so ore-poor planets believed ore was cheap
and refiners clustered there. Expected unit cost now divides by the local
planet attribute for both `output` and `success` effects; an attribute of
zero is non-viable locally. No commodity special-casing; the existing 20%
entry margin does the siting. Tests in `tests/test_imputed_cost.py`.

## 2026-07-12 - Ship fuel stranding: five bugs, not one

Largely fixed (fbef729, cc95633, 178f998). The correlated fleet draw-down
was stale cross-planet orders, a hold livelock, silent rescue bids, a
maintenance deadlock, fuel-desert idling, and a reserved-money leak. Fuel,
not cargo, was the money sink: price-aware bunkering and rationing,
depth-honest plans, maintenance pricing, and multi-tier repair bids ended
ships going broke.

## 2026-07-12 - Imputed replacement cost anchors bids for never-traded goods

Done (89689ed, b68e953). Never-traded intermediates deadlocked cold starts:
no price history, so no bids, so no production. Producers and consumer
drives now anchor on imputed replacement cost, which revived the upper
tiers. Medicine variance follow-up is in `TODO.md`.

## 2026-07-11 - Live galaxy view replaces the 3-pane inspector

Built (f4ebb7b to f8f686b). The static pygame inspector was deleted for a
live MOO-II-style galaxy view (`spacesim2/ui/live/`). Art comes from an
offline asset pipeline (`tools/assetgen/`) with a palette-snap
post-process; runtime loads only committed PNGs. See `docs/live-view.md`.

## 2026-06-09 - Price deflation fixed: sellers floor asks at replacement cost

Markets stopped deflating to 1 credit (58e863e). Actors price their own
labor into recipe costs, floor asks at replacement cost, and exit
loss-making production; buyer-side anti-deadlock fixes accompanied.

## 2026-06-06 - Shelter trade gap resolved via drive-backed WTP

Resolved (073ca54, a7481a5, a86da72). Shelter materials never traded
because brains had no shelter or health drive coverage and no
willingness-to-pay. Fix: two-layer drive WTP (deprivation stake times
buffer discount), scarcity pressure, market-maker liquidity across all
commodities, and ship maintenance-deadlock and repositioning fixes.

## 2026-06-06 - Dev-loop tooling landed; bit-exact determinism rejected

Landed (116306a and follow-ups): lazy pygame import, the `dev check`
umbrella, and later the notebook prune. Decided against bit-exact
determinism: randomness flows through `uuid4` and set iteration, so
seeding the module RNG gave false determinism and the `--seed` knob was
dropped. Assert with tolerances. The Tier-0 verdict is a catastrophe floor
(food and a live market), not an aspirational target.
