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
- Value the outbound burn honestly: units already in the tank at the galaxy
  fuel reference (`_fuel_value_reference`), units that must be bought at the
  local ask, however spiked. The ship still *buys* the whole round-trip
  shortfall. Rationing the purchase to this leg at scarcity prices, gated on
  the destination still being fuel-safe, was tried and rejected: it grounded
  the fleet (stranded 3 -> 14, departures 68 -> 22 over one 200-turn
  30-planet run), because a fuel-safe destination is a market with depth
  *now* and by arrival it usually has none.
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
# core/navigation.py). Multi-lane routes are flown in one go; intermediate
# planets are passed without docking.
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

### Lingering to fill the tank

A departing ship cancels its resting orders, so a bunker bid placed on the
turn the ship leaves buys nothing. When `decide_travel` is about to return a
destination - a loaded plan's, or the best destination for a hold of cargo -
`_linger_to_bunker` may return `None` instead and keep the ship docked one
more turn so that bid matches. It does so only when all of these hold:

- the tank is below `FUEL_LINGER_TANK_FRACTION` (50%) of capacity;
- the local ask is inside `FUEL_BUNKER_PREMIUM` and strictly below the
  reference;
- `_bunker_fillable_units` is positive: the minimum of tank room, what the
  cheap-tier budget affords at the bid, and one turn's supply, taken as the
  larger of the resting ask depth and the recent traded units per turn;
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
floor. All of them are gone. The one fuel-specific sale rule left is
`_sell_floor_price`: a `nova_fuel` ask never rests below the replacement
reference, `ceil(_fuel_value_reference())` or `FUEL_BID_FALLBACK_FLOOR`
(15) before anything has traded.

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
the turn's supply. Recent volume used to count as availability; on arrival
that was wrong 97% of the time, because the trade in the window is usually
the one that emptied the book. Two weaker signals exist for the callers that
genuinely want them:

- `Navigator.fuel_traded_recently(planet)`: fuel changed hands in
  `FUEL_MARKET_RECENCY_TURNS`. A supplier exists who might answer a standing
  bid. Used only by last-resort choices - deciding whether idling here is
  survivable, and ranking survival-reposition targets - never by a plan gate.
- `Market.has_price_signal(fuel)`: fuel has ever traded. The bottom tier of
  `_survival_reposition_target`.

`Navigator.fuel_ask_depth_at(planet)` gives the units resting on the ask
side, which is what an arriving ship could really buy.

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

1. `fuel_after_arrival` reaches the nearest *other* fuel seller - the escape
   leg, computed by `_arrival_fuel_requirement`; or
2. the destination is a **working fuel market**, which waives the escape leg
   entirely. That takes two independent signals: a live resting ask now
   (`_fuel_purchasable_at`) **and** fuel traded there recently
   (`Navigator.fuel_traded_recently`); or
3. fuel is purchasable nowhere else in the galaxy and `fuel_after_arrival`
   still covers the return leg to `return_planet`, less any shortfall the
   destination's own ask depth covers. Grounding the whole fleet would be
   worse than the risk.

Both halves of the waiver are load-bearing, and both failure modes are on
the record. Recency with no resting ask was the original stranding bug: it
said fuel was available on arrival when 97% of the time nothing was for
sale. Ask depth alone failed the other way: the book is read several turns
before the ship lands, and in a sixth of episodes the depth approved at
departure was gone by arrival. Do not weaken either half back to one signal.

Requiring the escape leg *unconditionally*, as the gate briefly did, is also
wrong: it self-ratchets. A ship holding exactly its escape leg can never
spend it, because the hop to the fuel seller then demands that seller's own
escape leg on arrival, and ships sat for hundreds of turns three units from
a live fuel market.

### Cargo before travel

Acquire cargo before deciding to travel. `decide_trade_actions()` evaluates
plans and places buy orders; `decide_travel()` checks for cargo and picks
the destination. Ships then never fly empty or without a plan.

### Sell location

Do not sell cargo where it was bought. Check other planets for a better
price (15% or more higher), hold and travel if worthwhile, and sell locally
only when no better destination exists.

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
