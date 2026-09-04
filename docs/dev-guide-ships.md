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

- Charge round-trip fuel to every plan.
- Execute only plans with margin at or above `TradePlan.MIN_MARGIN` (15%).
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
  `FUEL_BUNKER_PREMIUM` (30%) of the galaxy's cheapest believable fuel
  price, which is the min over current asks and 30-day averages backed by
  real trades (`_fuel_value_reference`). Bunkering beyond the survival
  target spends at most `FUEL_BUNKER_BUDGET_FRACTION` (50%) of cash so fuel
  does not crowd out trading capital.
- Ration at scarcity prices: buy only up to `_fuel_survival_target()`, the
  larger of two shortest round trips and the escape leg. Filling a tank at
  spike prices bankrupts ships.

Standing fuel rescue bids are capped at the survival target for the same
reason: a tank-sized bid reserves most of the ship's money while it rests
unfilled.

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
- After `DISTRESS_PATIENCE` (5) consecutive docked turns with no cargo, no
  plan and less money than one short round trip of fuel,
  `TraderBrain.is_distressed` turns on and `_sellable_quantity` lets the
  ship sell tank fuel down to `_fuel_survival_target()` instead of holding a
  full tank it cannot trade around. That converts parked working capital
  into cash without touching any fuel-safety gate, and selling only to the
  target keeps the next turn's top-up from re-buying what was just sold.
  Distress clears as soon as the ship has cash again.
  `TraderBrain._distress_entries` counts entries for analysis; a fleet-wide
  rise means capital is mis-sized.

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
    purchase_price_per_unit: int
    expected_sell_price_per_unit: int
    distance: float
    fuel_needed_one_way: int
    fuel_price_at_origin: int
    expected_maintenance_cost: int = 0

    # Computed properties:
    # - fuel_needed_round_trip
    # - total_fuel_cost
    # - total_purchase_cost
    # - expected_revenue
    # - expected_profit
    # - profit_margin
    # - is_profitable()   # expected_profit > 0 and margin >= MIN_MARGIN
```
