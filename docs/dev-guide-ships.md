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
| Fuel capacity | 50 units | Maximum fuel a ship can carry |
| Starting fuel | 30 units | Initial fuel for new ships |
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
