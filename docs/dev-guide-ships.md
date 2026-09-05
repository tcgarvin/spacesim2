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
| Fuel capacity | `BASE_FUEL_CAPACITY` (50) or more | Scales with the galaxy, see below |
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
  every planet looked scarcity-priced and no ship ever bunkered. Bunkering
  beyond the survival target spends at most `FUEL_BUNKER_BUDGET_FRACTION`
  (50%) of cash so fuel does not crowd out trading capital.
- Ration at scarcity prices: buy only up to `_fuel_survival_target()`, the
  larger of two shortest round trips and the escape leg. Filling a tank at
  spike prices bankrupts ships.

Standing fuel rescue bids are capped at the survival target for the same
reason: a tank-sized bid reserves most of the ship's money while it rests
unfilled.

Fuel upkeep, top-up or standing bid, runs *before* the plan branches in
`decide_trade_actions` whenever the tank is under `_fuel_reserve_need()`.
Every branch below it can return early - an accumulating plan holds the turn
for up to `ACCUMULATION_PATIENCE` turns - so upkeep placed after them never
ran for the ships that needed it most: a dry ship with a plan it could not
fly posted no rescue bid at all. Exactly one path owns the fuel side of the
book per turn: when upkeep ran, `_execute_trade_plan` is passed
`fuel_handled=True` and skips its own fuel buy and top-up rather than
double-bidding. Below the reserve `_sellable_quantity` yields no fuel, so
the early upkeep cannot self-trade against a same-turn fuel sell.

### Fuel as cargo

Tank fuel is normally not trade goods: only overflow above a full tank is,
or `_fuel_survival_target()` downward while a ship is distressed. Otherwise a
topped-up ship sells its tank at the local bid and re-buys at the ask every
other turn, bleeding the spread.

The exception is an explicit fuel run. `_fuel_delivery_in_progress` is true
at **both ends** of a `nova_fuel` `TradePlan`, and `_sellable_quantity` then
counts everything above `_fuel_sell_reserve()` - the travel reserve for the
trip. The origin end matters as much as the destination: a plan counts its
load through `_sellable_quantity`, so while only overflow counted at the
origin, a fuel plan never reached `_plan_loaded` and timed out after
`ACCUMULATION_PATIENCE` every single time. Fuel arbitrage was structurally
dead, on maps where a third to a half of planets have no fuel ask at all.

Counting as load is not permission to sell here: the plan lifecycle in
`decide_trade_actions` marks such a ship loaded and routes it to the plan's
destination, and `decide_travel` still gates the departure on the one-way
burn plus `_fuel_safe_destination`.

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
- `fuel_capacity_for(mean_distance, efficiency)`: an average round trip plus
  `FUEL_CAPACITY_ROUND_TRIP_HEADROOM`, never below `BASE_FUEL_CAPACITY`. The
  p90 lane route at 100 planets needs about 66 units round trip; sizing to
  that would fill most of the 100-unit hold with fuel, so long cross-galaxy
  hauls stay out of reach by design.

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
