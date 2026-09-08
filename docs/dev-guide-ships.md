# Ship Trading AI Development Guide

How to develop ship `Brain` classes for interplanetary trade. All symbols
below live in `core/ship.py` unless noted.

## Brain interface

A ship brain subclasses `ShipBrain` and implements:

- `decide_trade_actions() -> None`: place buy and sell orders at the current
  planet.
- `decide_travel() -> Optional[Planet]`: decide whether to travel and where.

## Patterns

### Plan-driven trading

Evaluate the whole cycle before buying: buy at origin, travel, sell at
destination. `TraderBrain` is the reference implementation.

- Charge the **outbound leg's** fuel to the plan's margin; the return leg is
  capital the next trade spends. Charging both legs to one haul killed real
  spreads whose quantity was flow-capped to a handful of units. The round
  trip is still *funded*: the cash gate in `_pair_economics` withholds
  round-trip fuel plus the refuel floor before a credit reaches cargo, and
  that gate is load-bearing against fleet insolvency. Do not relax it.
- `_pair_economics` funds `max(fuel_round_trip, fuel_one_way +
  arrival_requirement)`, capped at the tank, where `arrival_requirement` is
  `_arrival_fuel_requirement(destination, origin)` (the escape leg plus the
  maintenance buffer, zero at a station). A non-station destination can
  demand more than a bare round trip leaves in the tank, so funding only the
  round trip would reject every such pair at the fuel-safety gate below.
- Value the outbound burn honestly: units already in the tank at the galaxy
  fuel reference (`_fuel_value_reference`), units that must be bought at the
  local ask, however spiked. The ship still *buys* the whole round-trip
  shortfall. Rationing the purchase to this leg at scarcity prices, gated on
  the destination still being fuel-safe, was tried and rejected: it grounded
  the fleet (stranded 3 -> 14, departures 68 -> 22 over one 200-turn
  30-planet run), because a fuel-safe destination is a market with depth
  *now* and by arrival it usually has none.
- A pair that needs origin fuel bought at a spiked ask (not
  `_local_fuel_bunkerable`) while a station is reachable
  (`_can_reach_station`) is rejected outright: the ship should reach the
  station and plan from there instead of buying at the spike. The plan fuel
  step in `_execute_trade_plan` re-checks the same condition and funds the
  same `max(round trip, leg + arrival requirement)` quantity, capped at
  `Navigator.fuel_bid_ceiling()`, so a re-executed accumulating plan cannot
  drift past what the gate approved.
- Execute only plans with margin at or above `TradePlan.MIN_MARGIN` (15%).
- Separate the **bid** from the **cost basis**. `TradePlan.bid_price_per_unit`
  is what the ship posts, `max(best ask, flow price)`, deliberately high so
  the order also wins units out of the turn's flow.
  `TradePlan.purchase_price_per_unit` is what the cargo is expected to cost:
  the resting asks walked for the planned quantity (`Market.get_ask_levels`),
  any remainder at the bid. The evaluation price, not the bid, filters the
  destination's bids and flow; using the bid inflated the cost basis of every
  plan that had a real cheap ask behind it.
- Cap quantity at the destination's visible bid depth above cost and
  project revenue by walking the bid book (`Market.get_bid_levels`).
  Top-of-book times quantity overestimates on thin books.
- A plan with no resting destination bids is speculative and capped at
  `SPECULATIVE_PLAN_CAP` units.
- Price in expected maintenance through `TradePlan.expected_maintenance_cost`
  (2 departures times `MAINTENANCE_CHANCE` times the fuel-tier repair cost).
- With deferred matching the resting book holds only what the local auction
  rejected. Plans estimate from recent traded prices and volume
  (`DEMAND_HORIZON_TURNS`), bid into the auction at plan price, and fill
  over up to `ACCUMULATION_PATIENCE` docked turns.

### Checking market conditions

```python
# Get current bid/ask spread
bid, ask = market.get_bid_ask_spread(commodity)

# bid = highest buy order (what buyers will pay)
# ask = lowest sell order (what sellers want)

# Fallback to average if no orders
if bid is None:
    bid = market.get_avg_price(commodity)
```

### Fuel calculations

```python
# Shortest star-lane route, not the straight line (see core/galaxy.py and
# core/navigation.py). A multi-lane route is fuelled in one charge at
# departure and intermediate planets are passed without docking, except for
# the opportunistic refuel stop below.
distance = ship.route_distance(planet_a, planet_b)
fuel_needed = Ship.calculate_fuel_needed(distance)  # ceil(distance/20)

# Account for ship fuel efficiency (varies 0.8-1.2 per ship)
# Efficiency > 1.0 = better (uses LESS fuel)
# Efficiency < 1.0 = worse (uses MORE fuel)
adjusted_fuel = math.ceil(fuel_needed / ship.fuel_efficiency)

# Always plan for round-trip fuel (conservative)
fuel_round_trip = fuel_needed * 2
```

`Ship.fuel_required(distance)` applies the same rounding as departure; use
it when planning for a specific ship so planning and consumption agree.

### Fuel constants

| Constant | Value | Notes |
|----------|-------|-------|
| Base consumption | `ceil(distance/20)` | 1 fuel per 20 distance units |
| Fuel capacity | `BASE_FUEL_CAPACITY` (60) or more | Tank, separate from the hold; scales with the galaxy, see below |
| Starting fuel | `INITIAL_FUEL_FRACTION` (60%) of the tank | Initial fuel for new ships |
| Fuel efficiency | 0.8-1.2 | Random multiplier per ship |
| Maintenance cost | 5 fuel | `MAINTENANCE_CHANCE` (10%) per departure |
| Travel time | `ceil(distance/20)` turns | Independent of fuel |

### Fuel purchasing: bunker or ration

`TraderBrain._opportunistic_fuel_topup` buys fuel price-aware:

- Bunker (fill the tank) only when the local ask is within
  `FUEL_BUNKER_PREMIUM` (30%) of the galaxy's *typical* believable fuel
  price (`_fuel_value_reference`): the median over planets of each planet's
  30-day average price, or its best non-dealer ask with more than one unit
  of depth when it has never traded. This used to be the galaxy-wide
  minimum, which one-unit probe asks pinned far below the traded price, so
  every planet looked scarcity-priced and no ship ever bunkered.
- Ration at scarcity prices: buy only up to `_fuel_survival_target()`, the
  larger of two shortest round trips and the escape leg. Filling a tank at
  spike prices bankrupts ships.

The bid is `max(local ask, _flow_value(market, nova_fuel))`, the same rule
cargo bids use, for the required units and the bunker units alike. Matching
executes at the seller's ask and refunds the difference, so a bid above the
resting ask costs nothing on those units and also wins units out of the
turn's flow of fresh asks. Money is reserved at the bid, so every quantity is
sized on the bid rather than the ask. Measured over 300 turns at 100 planets,
bidding at the ask asked for 43.9k units and filled 3.9k.

The bunker budget beyond the survival target has two tiers, both fractions of
cash so fuel does not crowd out trading capital:

| Local ask | Fraction | Constant |
|-----------|----------|----------|
| at or below the reference | 80% | `FUEL_BUNKER_BUDGET_FRACTION_CHEAP` |
| above the reference, within the premium | 50% | `FUEL_BUNKER_BUDGET_FRACTION` |

Fuel bought at or under the typical galaxy price is not a loss to recover
later and the tank takes no hold space, so more of the purse is worth parking
there. Over the same 300 turns the fleet bought 3921 units through the bunker
path at 50 credits each and 1096 units through the survival ration at 243
each, 195k above reference: buying more where fuel is cheap is what removes
the expensive purchases.

### Fuel bid price ceiling

`Navigator.fuel_bid_ceiling()` caps every fuel bid a ship posts at
`FUEL_BID_CEILING_MULT` (2.0) times `fuel_value_reference()`, or at
`FUEL_BID_CEILING_UNBOUNDED` (`10**9`) when no planet has believable fuel
evidence, so a bootstrap galaxy with no fuel reference yet can still call the
first fuel into existence. Without the cap a resting bid buys its own
escalation: a seller fills the best resting bid at the bid price, so the fill
sets the next average price and the next bid goes higher still. The cap is
applied everywhere a ship prices fuel: `fuel_delivery_bid_price` and
`local_fuel_reference_price` in `Navigator`, and in `TraderBrain` the standing
rescue bid (`_post_standing_fuel_bid`), the opportunistic top-up
(`_opportunistic_fuel_topup`), and the plan fuel step
(`_execute_trade_plan`).

### No spiked buys when a station is reachable

A ship whose tank already covers `_departure_fuel_requirement` for some fuel
station is better off flying there than paying a spiked local ask:

- `TraderBrain._local_fuel_bunkerable(planet)` is true when a fuel ask rests
  at `planet` no higher than `FUEL_BUNKER_PREMIUM` times the galaxy
  reference. False covers both no ask and a spiked one.
- `TraderBrain._reachable_stations()` lists fuel stations elsewhere the tank
  alone can reach, nearest first, counting no local fuel purchase.
  `_can_reach_station()` is whether that list is non-empty.
- When the local ask is not `_local_fuel_bunkerable` and a station is
  reachable, `_opportunistic_fuel_topup` buys nothing, `_post_standing_fuel_bid`
  posts no standing bid, and the plan fuel step in `_execute_trade_plan`
  buys no fuel at the origin - each leaves fuel money for the reposition
  below instead. A ship mid refuel stop (`Ship.refuel_stop_resume` set) is
  exempt from the top-up cutoff and still buys, capped at
  `fuel_bid_ceiling()`; a ship with no reachable station (a trapped ship)
  also still buys, rationed to `_fuel_escape_target()`.

`TraderBrain._refuel_reposition_target()` chooses where to fly instead. It
returns a station when the ship is docked, not mid refuel stop, not already
at a station, the local ask is not `_local_fuel_bunkerable`, and the ship is
short of its survival target or its committed fuel need. Among
`_reachable_stations()`, it picks the one where the current hold's cargo is
worth most at bid-or-flow prices net of the leg's fuel at the galaxy
reference; an empty hold and ties go to the nearest station. Cargo aboard is
not unloaded for this.

`decide_trade_actions` computes the target once per docked turn and caches it
in `self._refuel_reposition`. If set, it takes the departure: any current
plan is dropped unless its destination is the station itself, local selling
and reposition intents are cleared, and `decide_travel` returns the station
directly - the ship does not adopt a new plan or evaluate the local sell
step first, since nothing it could do locally outranks being able to leave.
Measured over 400 turns, 46% of the fleet's spiked fuel spend had come from
ships that could already fly to a station under the departure gate and
posted a rescue bid instead.

### Stopping for fuel en route

A ship passing an intermediate planet with cheap fuel may dock there for a
turn, bunker, and fly on to its original destination.
`Ship.update_journey` finds the route nodes whose distance along the route
falls in the span covered this turn and offers each to
`ShipBrain.wants_refuel_stop`, which defaults to `False`; only `TraderBrain`
ever stops. `Ship._take_refuel_stop` performs the stop.

Departure charged `route_fuel_charged` for the whole route, so the stop
refunds what is not yet burned and the resumed leg is charged normally. Route
fuel is rounded up per leg, so splitting a route can cost fuel:
`shortfall = max(0, fuel_required(remaining) - refund)`.
`Ship._take_refuel_stop` allows up to `REFUEL_STOP_MAX_SHORTFALL` (2) units and
refuses more. Travel turns alone can only cost one unit, since
`ceil(total/20) <= ceil(covered/20) + ceil(remaining/20)`, but `fuel_required`
ceils a second time when it divides by fuel efficiency, so a ship under 1.0
efficiency can lose two. At a cap of one, that guard was refusing 25.6% of the
intermediate nodes ships passed at 40 planets; at two it refuses under 1%. The one unit is bought rather than treated as a reason to
fly on: the stop's criteria already establish a cheap ask with a deep book, so
it is the cheapest fuel the trip will see. The purchase goes in as the
top-up's `required_floor`, and `_refuel_stop_travel` holds the ship docked
until the tank covers the remaining route.

`TraderBrain.wants_refuel_stop` requires all of:

- the tank *after the refund* is below `FUEL_STOP_TANK_FRACTION` (60%) of
  capacity;
- a fuel ask rests at the planet, and the planet has a real price signal - one
  with no fuel history is passed by rather than guessed about;
- the ask is at or below the planet's own 30-day average, inside
  `FUEL_BUNKER_PREMIUM` of the galaxy reference, and strictly below that
  reference;
- the shortfall is affordable at the local bid and `_bunker_fillable_units` at
  the after-refund tank is at least `shortfall + 1`;
- the price gap on the units past the shortfall beats
  `_departed_trip_turn_value * stop_turns`, where `stop_turns` is 1 plus the
  travel turns the lane rounding adds.

`_departed_trip_turn_value` is recorded by `decide_travel` whenever it returns
a destination: `_trip_turn_value` of a loaded plan's expected profit, or of the
cargo destination's net value. An empty reposition records 0, so any positive
saving justifies a stop for a ship with nothing to lose.

While `Ship.refuel_stop_resume` is set the brain does fuel and nothing else.
`_refuel_stop_trade_actions` refreshes market facts, pumps, cancels resting
orders and runs `_opportunistic_fuel_topup` on the turn the ship docked, and
again on any later turn where the tank still does not cover the remaining
route; `take_turn` calls it from the traveling branch so the first bid rests
in the same turn's auction. `_current_plan`, `_plan_loaded`, `_addon_commodities` and
`_committed_fuel_need` are untouched, so arrival at the plan's destination
sells normally - the plan lifecycle would abandon the plan, since the stop is
not its origin. `_refuel_stop_travel` returns the resume destination once the
fill has been pumped and the leg is funded, and `take_turn` departs with
`start_journey(destination, resuming=True)`, which skips the maintenance roll
the original departure already made. A stop that has not resumed within
`REFUEL_STOP_MAX_TURNS` (3) turns is abandoned and the ship goes back to
normal docked logic; so is one whose resume destination is where the ship
already sits, and one interrupted by maintenance.

Stops are counted per ship in `Ship.refuel_stop_turns`, exposed as
`Ship.refuel_stops` and as `refuel_stops_window` in the KPI summary. They are
uncommon: 11 and 9 stops over 397 and 363 departures in two 40-planet,
150-turn runs, against 4 and 8 before the shortfall cap was raised to 2 and
the tank fraction to 0.6. What now refuses a stop is almost entirely supply:
86% and 87% of the intermediate nodes a ship passes have no resting fuel ask
at all. Every other criterion together accounts for under 10%.

### Lingering to fill the tank

A departing ship cancels its resting orders, so a bunker bid placed on the
turn the ship leaves buys nothing. When `decide_travel` is about to return a
destination - a loaded plan's, or the best destination for a hold of cargo -
`_linger_to_bunker` may return `None` instead and keep the ship docked one
more turn so that bid matches. It does so only when all of these hold:

- the tank is below `FUEL_LINGER_TANK_FRACTION` (50%) of capacity;
- the local ask is inside `FUEL_BUNKER_PREMIUM` and strictly below the
  reference;
- `_bunker_fillable_units(bid, planet, tank)` is positive: the minimum of tank
  room, what the cheap-tier budget affords at the bid, and one turn's supply,
  taken as the larger of the resting ask depth and the recent traded units per
  turn;
- fillable units times the price gap beats `_trip_turn_value`, the trip's
  expected profit spread over `2 * travel_turns + 1`.

An empty reposition has no such profit number, so it never lingers.

A stop gets at most one linger turn. `_fuel_linger_planet` records where it
was spent and is cleared as soon as the ship is docked anywhere else;
`_fuel_linger_pending` marks the turn just bought and is consumed at the top
of the next `decide_trade_actions`, where it also stops the linger counting
against a loaded plan's departure patience (`_plan_turns_left`). A lingering
ship still posts its bunker bid on the linger turn: a loaded plan reaches the
`_maintain_fuel()` call at the end of `decide_trade_actions`, and a ship
holding cargo for a better market reaches the same call.

Standing fuel rescue bids are capped at the survival target for the same
reason: a tank-sized bid reserves most of the ship's money while it rests
unfilled.

Fuel upkeep, top-up or standing bid, runs *before* the plan branches in
`decide_trade_actions` whenever the tank (`Ship.fuel`) is under
`_fuel_reserve_need()`.
Every branch below it can return early - an accumulating plan holds the turn
for up to `ACCUMULATION_PATIENCE` turns - so upkeep placed after them never
ran for the ships that needed it most: a dry ship with a plan it could not
fly posted no rescue bid at all. Exactly one path owns the fuel side of the
book per turn: when upkeep ran, `_execute_trade_plan` is passed
`fuel_handled=True` and skips its own fuel buy and top-up rather than
double-bidding. The tank is never for sale, so the early upkeep cannot
self-trade against a same-turn fuel sell; a ship selling hold fuel skips the
top-up that turn (`placed_fuel_sell`).

### The tank is not the hold

`Ship.fuel` is the tank: what departures burn and what every fuel gate
reads. It is separate from `Ship.cargo`, takes no hold space, and is never
for sale. `nova_fuel` in the hold is trade goods like any other commodity.

Market fills land in the hold, so `Ship.pump_fuel` moves hold fuel into the
tank up to capacity at the start of every docked turn (`Ship.take_turn`,
and again at the top of `decide_trade_actions` and `decide_travel` so tests
that drive the brain directly see the same state). It leaves
`ShipBrain.fuel_cargo_to_keep()` units in the hold: for `TraderBrain` that
is the plan quantity at either end of a `nova_fuel` `TradePlan`, so a fuel
run's load is not pumped away, and zero otherwise. Hold fuel the tank
cannot take stays in the hold and sells with the rest of the cargo.

`_sellable_quantity` is therefore just the hold count for every commodity.
Before the split, tank fuel was cargo and the brain carried a set of rules
to keep it from being sold: an overflow-only rule, a scarcity-bid gate, a
delivery-plan exception, a distress liquidation path, and a committed-fuel
floor. All of them are gone. The one fuel-specific sale rule left is in
`_sell_floor_price` (see "Cost basis and the sell floor" below): a
`nova_fuel` ask never rests below the replacement reference,
`ceil(_fuel_value_reference())` or `FUEL_BID_FALLBACK_FLOOR` (15) before
anything has traded, on top of the cost-basis floor every commodity gets.

Fuel buys are bounded by tank room and money, never by hold room. A fuel
fill can briefly put the hold over `cargo_capacity`; the pump clears it
before any decision runs.

### Add-on cargo

A plan's quantity is capped by the destination's bid depth plus flow, and
that cap usually binds, so a ship on a plan left most of its hold empty:
measured over 400 turns at 100 planets, the median hold at departure was
21% full and a second commodity to the same destination had positive
marginal profit at 84% of departures. `_execute_trade_plan` now fills the
rest of the hold with `_place_addon_bids`:

- Candidates come from `_addon_candidates`: every exportable commodity at
  the origin other than the plan's, fuel, and anything the ship is listing
  here, evaluated by `_evaluate_trade_opportunity` against the plan's
  destination with a `_PairEconomics` that carries the leftover money and
  space and no fuel to buy. The trip is already paid for, so an add-on is
  judged on revenue minus purchase cost and must clear
  `TradePlan.MIN_MARGIN` on its purchase cost alone.
- Up to `ADDON_MAX_COMMODITIES` (3) are chosen greedily by marginal profit,
  the space each takes is deducted, and the rest are re-evaluated.
- Chosen commodities are recorded in `_addon_commodities` and skipped by
  the local sell step while the plan accumulates, so the ship does not list
  at the origin what it just bought there. The set is cleared when a plan
  is adopted or dropped. Add-ons are chosen once per plan and not re-bid
  on later accumulating turns; a partly filled add-on flies as is.
- Loading and departure are still gated on the primary plan alone.
  `decide_travel` already values a mixed hold per commodity, and arrival
  sells everything.

### Where fuel can actually be bought

`Navigator.fuel_purchasable_at` means a **live resting ask**, nothing else.
Actors trade before ships each turn, so the book a ship reads already holds
the turn's supply.

`Navigator.fuel_ask_depth_at(planet)` gives the units resting on the ask
side, which is what an arriving ship could really buy.

A single live ask is not enough to plan an escape leg around: a one-unit
producer ask or a spiked book cannot refill a tank. `Navigator.fuel_station_at`
is the stricter test a ship commits an escape leg to:

- at least `FUEL_STATION_MIN_DEPTH` (6) units resting on the ask side, from
  any seller, and
- the best ask no more than `FUEL_STATION_MAX_PRICE_MULT` (2.0) times
  `Navigator.fuel_value_reference()`; with no reference, depth alone decides.

`Navigator.nearest_fuel_station_distance(planet)` returns the distance to the
nearest other station, or `None` if the galaxy has none.
`Navigator.fuel_station_planets()` lists every current station.

Two weaker signals exist for callers that genuinely want them, never a plan
gate:

- `Navigator.fuel_traded_recently(planet)`: fuel changed hands in
  `FUEL_MARKET_RECENCY_TURNS`. A supplier exists who might answer a standing
  bid. Used only by last-resort choices - deciding whether idling here is
  survivable, and ranking survival-reposition targets.
- `Market.has_price_signal(fuel)`: fuel has ever traded. The bottom tier of
  `_survival_reposition_target`.

### Capital scaled to the galaxy

Ships are launched by `Simulation._setup_ships` with money and a tank sized
for the galaxy they will fly in, from `Navigator.mean_pair_distance()`:

- `starting_capital(mean_distance, efficiency)`:
  `SHIP_CAPITAL_ROUND_TRIPS` (3) average round trips of fuel plus their
  expected maintenance, valued at `SHIP_CAPITAL_FUEL_PRICE_REFERENCE` (40
  credits a unit, the price a five-planet galaxy was tuned at), marked up by
  `SHIP_CAPITAL_RESERVE_FRACTION` for cargo, floored at `SHIP_CAPITAL_FLOOR`
  (1000). A mean round trip burns about 5 fuel units at 5 planets and about
  30 at 100, and every plan must fund round-trip fuel before a credit goes
  to cargo, so a fixed 1000-credit purse grounded most of a 100-planet
  fleet.
- `fuel_capacity_for(mean_distance, efficiency)`:
  `FUEL_CAPACITY_ROUND_TRIP_HEADROOM` (3.0) average round trips, never below
  `BASE_FUEL_CAPACITY` (60). The tank costs no hold space, so it is sized
  for several trips: a ship bunkers where fuel is cheap and can fly past
  spiked markets. Before the split the tank was 1.5 round trips and shared
  the hold, and spiked survival top-ups were 252k of the fleet's 266k fuel
  premium over 600 turns at 100 planets.

A `Ship` built directly, as tests do, keeps the constant defaults.

### Distress: the exit from bankruptcy

Bankruptcy used to be absorbing. `_pair_economics` needs cash for
round-trip fuel, a refuel floor and maintenance before any cargo, and
`_find_reposition_target` plans through the same gate, so a ship whose money
fell below the floor could neither trade nor move, and had no income.

Two things prevent that:

- The refuel floor is charged only on the reserve the trip does not leave in
  the tank. Fuel already aboard is not re-charged in cash, so a full-tank
  ship is not priced out of every pair when fuel spikes.
- After `DISTRESS_PATIENCE` (5) consecutive docked turns with no non-fuel
  cargo and less money than one short round trip of fuel,
  `TraderBrain.is_distressed` turns on and `_sellable_quantity` lets the
  ship sell tank fuel down to `_fuel_survival_target()` instead of holding a
  full tank it cannot trade around. That converts parked working capital
  into cash without touching any fuel-safety gate, and selling only to the
  target keeps the next turn's top-up from re-buying what was just sold.
  `TraderBrain._distress_entries` counts entries for analysis; a fleet-wide
  rise means capital is mis-sized.
- While distressed, `_plan_acceptable` drops `TradePlan.MIN_MARGIN` (15%) to
  a plain profit test: any haul that more than covers its own fuel and
  maintenance is worth flying for a parked ship. Nothing about safety moves -
  the round-trip cash gate in `_pair_economics` still sizes the haul to the
  cash on hand, and every fuel gate is untouched.

Entering and leaving distress are deliberately different tests. Entering
needs an idle, empty, below-floor turn; leaving needs **cash at or above
`_short_trip_cash_floor()`** and nothing else. Clearing on cargo alone was a
bug: a ship that won a few units into its hold left distress while still
unable to fund a trip, lost the wider selling and margin rules that were
about to move it, and fell straight back in. Holding a plan has never
cleared the condition, since an unfillable plan is re-adopted every turn and
the ships most in need of the exit were the ones that could never reach it.

### Fuel-safe destinations

`_fuel_safe_destination(destination, return_planet, fuel_after_arrival)`
gates every departure, in `_pair_economics`, `decide_travel`, the hold-cargo
comparison and `_find_reposition_target`. Everywhere it is asked about a
docked ship's *reach*, reach means the tank plus `_affordable_local_fuel()` -
what the ship could buy here, bounded by hold room, 90% of its money at the
local ask, and tank capacity. Judging reach on the tank alone was the
largest single source of idle turns: ships with cash and a fuel ask in front
of them could neither plan nor reposition. `_find_reposition_target` charges
that purchase against the plan the origin backs, and
`_reposition_destination` records the chosen origin in
`_reposition_intent` so the next docked turn funds it through
`_committed_fuel_need`, the same mechanism a held cargo uses. A destination is safe when:

1. `fuel_after_arrival` reaches the nearest *other* fuel station
   (`Navigator.fuel_station_at`, via `Navigator.nearest_fuel_station_distance`)
   - the escape leg, computed by `_arrival_fuel_requirement`, plus the
   maintenance buffer described below; or
2. the destination is itself a fuel station, which waives the escape leg
   entirely: a station has depth enough to refill a tank at a price near the
   galaxy reference, so any fuel spent there is re-buyable; or
3. the galaxy has no station at all and `fuel_after_arrival` still covers the
   return leg to `return_planet`, less any shortfall the destination's own
   ask depth covers. Grounding the whole fleet would be worse than the risk.

The waiver used to fire on a live resting ask plus recent trading at the
destination. That let ships land on a market that had a resting ask at
departure and nothing left by arrival: 39% of the fleet's spiked fuel spend
came from ships that had waived their escape leg this way. Requiring the
depth-and-price test of a station instead closes that gap.

Requiring the escape leg *unconditionally*, with no waiver at all, is also
wrong: it self-ratchets. A ship holding exactly its escape leg can never
spend it, because the hop to the fuel seller then demands that seller's own
escape leg on arrival, and ships sat for hundreds of turns three units from
a live fuel market.

### Maintenance buffer and repair kit

A departure rolls `MAINTENANCE_CHANCE` (10%) for a maintenance event, and the
event is resolved the turn after departure, so a ship funded to land with
exactly its escape leg can be short of it before it can requeue for fuel.
`TraderBrain._arrival_fuel_requirement` adds a buffer on top of the escape
leg to cover this:

- `TraderBrain._maintenance_fuel_buffer()` returns `MAINTENANCE_FUEL_UNITS`
  (5), the fuel-tier repair cost, unless the ship holds a complete repair
  kit, in which case it returns 0.
- `TraderBrain._holds_repair_kit()` and `_repair_kit_tier()` check the hold
  against `MAINTENANCE_KIT_TIERS` - `ship_components` (1 unit),
  `ship_parts` (2), `ship_supplies` (3), best quality first, the same order
  `Ship.perform_maintenance` tries them in. `MAINTENANCE_TIERS` is those
  three plus the legacy `nova_fuel` (`MAINTENANCE_FUEL_UNITS`) tank-fuel
  tier, which is what the buffer exists to survive.
- `TraderBrain._buy_repair_kit()` buys the cheapest complete tier with a
  resting ask, once per turn, whenever its cost is below
  `MAINTENANCE_FUEL_UNITS` valued at the galaxy fuel reference: owning a kit
  removes the buffer from every arrival requirement this ship funds, so a
  kit that costs less than the buffer it removes pays for itself
  immediately. Runs in `decide_trade_actions` ahead of cargo listing and
  cargo buying.
- The held kit is excluded from `_sellable_quantity`, so a ship does not
  list the maintenance tier it would repair itself with; a second, spare
  unit of the same commodity still sells.

### Cargo before travel

Acquire cargo before deciding to travel. `decide_trade_actions()` evaluates
plans and places buy orders; `decide_travel()` checks for cargo and picks
the destination. Ships then never fly empty or without a plan.

### Cost basis and the sell floor

`TraderBrain` keeps a per-commodity cost basis fed from this ship's own
fills: `_ingest_cost_basis()` reads new fills into it once per docked turn,
before any decision uses it. The cursor is the highest transaction id
already seen per planet (`_basis_cursors`, keyed by planet name), not an
index, since the market trims each per-actor history from the front. A buy
raises the basis (`units`, `credits`); a sell removes units at the average
cost (`_reduce_cost_basis`). Fuel is excluded from the basis; the tank is
priced at the galaxy reference, not at what it cost. `basis_per_unit(commodity)`
returns credits per unit, or `None` for cargo with no known basis (aboard
before tracking started, or never bought on a market).

`_sell_floor_price(commodity)` is the lowest price the ship will list at:

- Cargo with a known basis floors at that basis, marked down `UNSOLD_DECAY`
  (10%) per docked turn it has sat listed and unfilled, never below
  `LIQUIDATION_FLOOR` (40%) of basis. `_age_unsold_listings()` counts a turn
  against a commodity only when the held quantity has not fallen below what
  was listed (`_listed_held`, set by `_note_listed()` when an ask goes in); a
  fill on either side resets `_unsold_turns` for that commodity in
  `_ingest_cost_basis()`.
- Fuel additionally floors at the galaxy fuel reference,
  `ceil(_fuel_value_reference())` or `FUEL_BID_FALLBACK_FLOOR` (15) before
  anything has traded, and takes the higher of the two floors.
- Cargo with no known basis has no floor.

### Selling cargo locally

`_place_flow_sell_orders` ladders an ask into every resting bid level at or
above the floor, one order per level, so a single ask does not liquidate the
whole load into a 1-credit probe bid. Whatever is left rests at
`max(floor, min(flow_px, best_bid))`: no higher than the live best bid, and
no higher than the haircut flow price (`SELL_PRICE_HAIRCUT`, 0.9x recent
clearing). An ask above every live bid is a forecast, not a sale; the floor
is the one thing that can put an ask there anyway.

### Realizable value and holding cargo for another market

`_realizable_value(market, commodity, quantity)` prices a quantity the way
it would actually sell: bid levels walked from the top for as many units as
they hold, and any remainder priced at what `_place_flow_sell_orders` would
rest it at, `min(flow_px, best_bid)`. A market with neither a bid nor a flow
price values the remainder at nothing. This replaced `max(best_bid, flow) *
quantity`, which paid the top bid for the whole load and ignored depth.

`_cargo_disposition` decides whether to sell the hold here or hold it for
another planet, using `_realizable_value` on both sides: the local value of
each held commodity against, for every other planet the ship can reach
(`_departure_fuel_requirement`), that planet's realizable value net of the
leg's fuel cost. Holding wins only when the destination's net beats the
local value by 15% or more, and a loaded plan's cargo is not compared here —
it flies to `plan.destination`. A commodity that has already made
`MAX_CARGO_HOPS` (1) hops is skipped and defaults to selling locally: cargo
that keeps hopping burns fuel on every leg against a price that has usually
gone by arrival. `decide_travel`'s cargo branch (an unloaded hold, not under
a plan) values `cargo_to_sell` at each candidate destination the same way,
with `_realizable_value`, and counts a hop in `_cargo_hops` per commodity
when it picks a destination.

A ship left holding cargo for another market that cannot depart —
`_cargo_disposition` said hold, but the fuel gate refuses each turn — is not
held forever. `_hold_planet` and `_hold_refused_turns` count consecutive
docked turns at that planet with the hold still refused; once
`_hold_refused_turns` reaches `HOLD_PATIENCE` (3), `decide_trade_actions`
overrides the hold and sells locally instead.

A loaded plan whose departure the fuel gate would refuse this turn is
listed locally too: `_plan_departure_blocked(plan)` applies the same fuel
and safety test `decide_travel`'s plan branch does, checked early in
`decide_trade_actions` so the cargo goes in the book instead of sitting
unlisted for `ACCUMULATION_PATIENCE` turns waiting on a departure that will
not happen this turn. Listing costs nothing when the plan does leave later,
since `start_journey` cancels resting orders before departure.

## Common pitfalls

| Pitfall | Solution |
|---------|----------|
| Immediate selling | Check destinations before selling at origin |
| Insufficient fuel | Verify fuel before traveling |
| Ignoring fuel costs | Factor fuel into every profit calculation |
| No fallback action | Always have a default (buy fuel, wait) |
| Forgetting order delays | Cargo arrives the turn after orders are placed |

## Expected trading behavior

- Profitable trades are not guaranteed early. Ships may wait 10-50 turns
  for a first opportunity, and some ships lose money.
- More planets mean more opportunities.
- Ships do not trade when spreads are too small, when there are bids but no
  asks, when other ships bought the goods first, or when fuel erases the
  margin.

## Debugging ships that do not trade

```python
# Check if profitable opportunities exist
for ship in sim.ships:
    plan = ship.brain._find_best_trade_plan()
    if plan:
        print(f'{ship.name}: Found trade worth {plan.expected_profit}')
    else:
        # Why no trade? Check market conditions
        food = sim.commodity_registry.get_commodity('food')
        for planet in sim.planets:
            bid, ask = planet.market.get_bid_ask_spread(food)
            print(f'{planet.name}: bid={bid}, ask={ask}')
```

If `ask` is `None` on every planet, no one is selling. That is normal early
in a run or with too few market makers.

## TradePlan

The `TradePlan` dataclass holds one complete trade opportunity:

```python
@dataclass
class TradePlan:
    origin: Planet
    destination: Planet
    commodity: CommodityDefinition
    quantity: int
    bid_price_per_unit: int       # what the ship posts
    purchase_price_per_unit: int  # what the cargo is expected to cost
    expected_sell_price_per_unit: int
    distance: float
    fuel_needed_one_way: int
    fuel_price_at_origin: int     # local ask: what fuel bought here costs
    fuel_units_from_tank: int     # of the outbound burn, units already aboard
    fuel_price_from_tank: int     # galaxy fuel reference
    expected_maintenance_cost: int = 0

    # Computed properties:
    # - fuel_needed_round_trip    # what the cash gate funds
    # - total_fuel_cost           # the OUTBOUND leg only, mixed-priced
    # - total_purchase_cost
    # - expected_revenue
    # - expected_profit
    # - profit_margin
    # - is_profitable()   # expected_profit > 0 and margin >= MIN_MARGIN
```
