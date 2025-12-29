# Ship Trading AI Development Guide

This guide covers developing ship `Brain` classes for interplanetary trade.

## Brain Interface

Ship brains (subclasses of `ShipBrain`) must implement:
- `decide_trade_actions() -> None` - Place buy/sell orders at current planet
- `decide_travel() -> Optional[Planet]` - Decide whether to travel and where

## Key Patterns

### 1. Plan-Driven Trading (recommended)

Evaluate complete trade cycles BEFORE buying:
```
origin → buy goods → travel → sell goods
```

- Account for round-trip fuel costs (conservative planning)
- Only execute trades with minimum profit margin (e.g., 15%+)
- Example: `TraderBrain` in `ship.py`

### 2. Checking Market Conditions

```python
# Get current bid/ask spread
bid, ask = market.get_bid_ask_spread(commodity)

# bid = highest buy order (what buyers will pay)
# ask = lowest sell order (what sellers want)

# Fallback to average if no orders
if bid is None:
    bid = market.get_avg_price(commodity)
```

### 3. Fuel Calculations

```python
distance = Ship.calculate_distance(planet_a, planet_b)
fuel_needed = Ship.calculate_fuel_needed(distance)  # ceil(distance/20)

# Account for ship fuel efficiency (varies 0.8-1.2 per ship)
# Efficiency > 1.0 = better (uses LESS fuel)
# Efficiency < 1.0 = worse (uses MORE fuel)
adjusted_fuel = math.ceil(fuel_needed / ship.fuel_efficiency)

# Always plan for round-trip fuel (conservative)
fuel_round_trip = fuel_needed * 2
```

### Fuel System Constants

| Constant | Value | Notes |
|----------|-------|-------|
| Base consumption | `ceil(distance/20)` | 1 fuel per 20 distance units |
| Fuel capacity | 50 units | Maximum fuel a ship can carry |
| Starting fuel | 30 units | Initial fuel for new ships |
| Fuel efficiency | 0.8-1.2 | Random multiplier per ship |
| Maintenance cost | 5 fuel | 10% chance per departure |
| Travel time | `ceil(distance/20)` turns | Independent of fuel |

### 4. Cargo-Before-Travel Pattern

- Ships should acquire cargo BEFORE deciding to travel
- In `decide_trade_actions()`: evaluate trades and place buy orders
- In `decide_travel()`: check if have cargo, then pick best destination
- This ensures ships don't travel empty or without a plan

### 5. Sell Location Strategy

- Don't sell cargo immediately upon acquisition
- Check if better prices exist at other planets (>15% higher)
- Hold cargo and travel if worthwhile
- Only sell locally if no better destination exists

## Common Pitfalls

| Pitfall | Solution |
|---------|----------|
| Immediate selling | Don't sell at origin - check destinations first |
| Insufficient fuel | Verify fuel before traveling |
| Ignoring fuel costs | Factor fuel into all profit calculations |
| No fallback action | Always have default (buy fuel, wait) |
| Forgetting order delays | Cargo arrives NEXT turn after placing orders |

## Economic Dynamics & Profitability

**Expected Trading Behavior**:
- Profitable trades are **not guaranteed** in early turns - markets need time to develop price differentials
- Ships may wait many turns (10-50+) before finding profitable opportunities
- Some ships will lose money - realistic trading has winners and losers
- With 5+ planets, expect more frequent trading opportunities than with 2 planets

**Why Ships Don't Trade Immediately**:
1. **Insufficient price spreads**: All planets produce similar goods at similar prices initially
2. **No sellers**: Markets may have buy orders (bids) but no sell orders (asks)
3. **Competition**: Other ships may buy available goods before your ship's turn
4. **Fuel costs**: Even with price differential, fuel costs can eliminate profit margin

## Debugging "Ships Not Trading"

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

If `ask=None` for all planets, no one is selling - this is normal in early simulation or with insufficient market makers.

## TradePlan Class

The `TradePlan` dataclass (in `ship.py`) represents a complete trade opportunity:

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

    # Computed properties:
    # - fuel_needed_round_trip
    # - total_fuel_cost
    # - total_purchase_cost
    # - expected_revenue
    # - expected_profit
    # - profit_margin
    # - is_profitable(min_margin=0.15)
```
